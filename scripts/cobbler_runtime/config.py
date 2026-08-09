"""Config loading and role-route resolution with explicit provenance.

Precedence (highest wins):
1. Survival Guide route snapshot / explicit project required values
2. Local ignored `.elves/models.toml`
3. Installed/user `config.json`
4. Native host defaults

Local TOML preference uses stdlib ``tomllib`` when available and the shipped,
stdlib-only generated-subset parser on Python 3.10.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import default_profiles, get_adapter
from .dispatch import LaneSpec
from .context import validate_credential_grant_names
from .schema import (
    DEFAULT_ROLES,
    NATIVE_PROFILE_NAME,
    ConfigSource,
    ContextSharingPolicy,
    EffectiveAttempt,
    FallbackEntry,
    HarnessProfile,
    ResolvedConfig,
    RoleName,
    RoleRoute,
    SessionMode,
    ValidationIssue,
    build_effective_attempts,
    parse_role_name,
)
from .toml_compat import loads as load_toml_text


SOURCE_RANK: dict[ConfigSource, int] = {
    ConfigSource.SURVIVAL_GUIDE: 4,
    ConfigSource.LOCAL_MODELS_TOML: 3,
    ConfigSource.USER_CONFIG_JSON: 2,
    ConfigSource.NATIVE_DEFAULT: 1,
}


def native_defaults() -> dict[str, RoleRoute]:
    """Every role resolves to host-native when no external config exists."""
    return {
        role.value: RoleRoute(
            role=role,
            profile=NATIVE_PROFILE_NAME,
            required=False,
            fallback_chain=(),
            source=ConfigSource.NATIVE_DEFAULT,
            session_mode=SessionMode.EPHEMERAL,
            notes="Public default: host-native with zero external tools",
        )
        for role in DEFAULT_ROLES
    }


def _as_mapping(value: Any, *, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValidationIssue(
            "invalid_type",
            f"Expected a table/object at `{path}`",
            path=path,
            hint="Use a TOML table or JSON object",
        )
    return dict(value)


def _as_bool(value: Any, *, path: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValidationIssue(
        "invalid_type",
        f"Expected boolean at `{path}`",
        path=path,
    )


def _as_str(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationIssue(
            "invalid_type",
            f"Expected non-empty string at `{path}`",
            path=path,
        )
    return value.strip()


def _parse_fallback_chain(raw: Any, *, path: str) -> tuple[FallbackEntry, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationIssue(
            "invalid_type",
            f"Expected list at `{path}`",
            path=path,
        )
    entries: list[FallbackEntry] = []
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        if isinstance(item, str):
            entries.append(FallbackEntry(profile=item.strip()))
            continue
        if isinstance(item, Mapping):
            profile = _as_str(item.get("profile") or item.get("route"), path=f"{item_path}.profile")
            reason = str(item.get("reason") or "")
            entries.append(FallbackEntry(profile=profile, reason=reason))
            continue
        raise ValidationIssue(
            "invalid_type",
            f"Fallback entry must be a string or object at `{item_path}`",
            path=item_path,
        )
    return tuple(entries)


def _parse_str_tuple(raw: Any, *, path: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(parts)
    if not isinstance(raw, list):
        raise ValidationIssue(
            "invalid_type",
            f"Expected list or comma-string at `{path}`",
            path=path,
        )
    values: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise ValidationIssue(
                "invalid_type",
                f"Expected non-empty string at `{path}[{index}]`",
                path=f"{path}[{index}]",
            )
        values.append(item.strip())
    return tuple(values)


def _parse_role_override(
    role_name: str,
    raw: Any,
    *,
    source: ConfigSource,
    path: str,
) -> RoleRoute:
    role = parse_role_name(role_name)
    if isinstance(raw, str):
        return RoleRoute(
            role=role,
            profile=raw.strip(),
            required=False,
            fallback_chain=(),
            source=source,
        )
    data = _as_mapping(raw, path=path)
    profile = _as_str(
        data.get("profile") or data.get("preference") or data.get("route"),
        path=f"{path}.profile",
    )
    # required: true is valid only from the active Survival Guide route source.
    raw_required = data.get("required")
    if raw_required is not None and source != ConfigSource.SURVIVAL_GUIDE:
        # Ignore silent mandatory elevation from user/global preference config.
        required = False
    else:
        required = _as_bool(raw_required, path=f"{path}.required", default=False)
    fallback = _parse_fallback_chain(
        data.get("fallback_chain") or data.get("fallback") or data.get("fallback-chain"),
        path=f"{path}.fallback_chain",
    )
    session_raw = data.get("session_mode") or data.get("session-mode")
    if session_raw is None:
        session_mode = SessionMode.EPHEMERAL
    else:
        try:
            session_mode = SessionMode(str(session_raw).strip().lower().replace("-", "_"))
        except ValueError as exc:
            raise ValidationIssue(
                "invalid_session_mode",
                f"Unknown session mode `{session_raw}`",
                path=f"{path}.session_mode",
            ) from exc
    notes = str(data.get("notes") or "")
    return RoleRoute(
        role=role,
        profile=profile,
        required=required,
        fallback_chain=fallback,
        source=source,
        session_mode=session_mode,
        notes=notes,
    )


def _parse_profiles(
    raw: Any,
    *,
    source: ConfigSource,
    path: str,
    existing: dict[str, HarnessProfile],
    warnings: list[str] | None = None,
) -> dict[str, HarnessProfile]:
    data = _as_mapping(raw, path=path)
    parsed: dict[str, HarnessProfile] = {}
    warn_sink = warnings if warnings is not None else []
    for name, body in data.items():
        profile_path = f"{path}.{name}"
        if name in existing and existing[name].adapter != "host-native" and source != ConfigSource.SURVIVAL_GUIDE:
            # Allow redefinition only when adapter stays consistent or is explicit.
            pass
        if name in parsed:
            raise ValidationIssue(
                "duplicate_profile",
                f"Duplicate profile name `{name}`",
                path=profile_path,
                hint="Profile names must be unique within a config source",
            )
        if isinstance(body, str):
            adapter_name = body.strip()
            body_map: dict[str, Any] = {"adapter": adapter_name}
            provided: set[str] = {"adapter"}
        else:
            body_map = _as_mapping(body, path=profile_path)
            provided = set(body_map.keys())
            # Normalize aliases into canonical provided field names.
            if "model" in provided and "requested_model" not in provided:
                provided.add("requested_model")
            if "args" in provided or "extra-args" in provided:
                provided.add("extra_args")
            if "env" in provided or "environment" in provided or "named_env" in provided:
                provided.add("env_grants")
            if "input" in provided:
                provided.add("input_contract")
            if "output" in provided:
                provided.add("output_contract")
            if "harness" in provided:
                provided.add("adapter")
            if "session-mode" in provided:
                provided.add("session_mode")
            if "context-sharing" in provided:
                provided.add("context_sharing")
            if "qualified_capabilities" in provided or "qualified" in provided:
                provided.add("qualified_capabilities")
        adapter_name = _as_str(
            body_map.get("adapter") or body_map.get("harness") or name,
            path=f"{profile_path}.adapter",
        )
        if "adapter" not in provided and "harness" not in provided and isinstance(body, Mapping):
            # adapter defaulted from profile name — not an explicit field.
            provided.discard("adapter")
        # Validate adapter exists (custom-cli and built-ins).
        try:
            get_adapter(adapter_name if adapter_name in {
                "claude-code", "grok-build", "codex-fugu", "custom-cli", "host-native", "devin-cli", "omp-cli"
            } else "custom-cli")
        except ValidationIssue:
            raise
        # If adapter is not a known built-in name, treat as custom-cli wrapper.
        if adapter_name not in {
            "claude-code",
            "grok-build",
            "codex-fugu",
            "custom-cli",
            "host-native",
            "devin-cli", "omp-cli",
        }:
            # Named custom profiles still use the custom-cli adapter contract.
            resolved_adapter = "custom-cli"
        else:
            resolved_adapter = adapter_name
            get_adapter(resolved_adapter)

        executable = body_map.get("executable")
        if executable is not None and not isinstance(executable, str):
            raise ValidationIssue(
                "invalid_type",
                f"executable must be a string at `{profile_path}.executable`",
                path=f"{profile_path}.executable",
            )
        notes = str(body_map.get("notes") or "")
        enabled = _as_bool(body_map.get("enabled"), path=f"{profile_path}.enabled", default=True)
        requested_model = body_map.get("requested_model") or body_map.get("model")
        if requested_model is not None and not isinstance(requested_model, str):
            raise ValidationIssue(
                "invalid_type",
                f"requested_model must be a string at `{profile_path}.requested_model`",
                path=f"{profile_path}.requested_model",
            )
        if isinstance(requested_model, str):
            requested_model = requested_model.strip() or None
        extra_args = _parse_str_tuple(
            body_map.get("extra_args") or body_map.get("args") or body_map.get("extra-args"),
            path=f"{profile_path}.extra_args",
        )
        env_grants_path = f"{profile_path}.env_grants"
        env_grants = _parse_str_tuple(
            body_map.get("env_grants")
            or body_map.get("env")
            or body_map.get("environment")
            or body_map.get("named_env"),
            path=env_grants_path,
        )
        env_grants = validate_credential_grant_names(
            env_grants,
            path=env_grants_path,
        )
        capabilities = _parse_str_tuple(
            body_map.get("capabilities"),
            path=f"{profile_path}.capabilities",
        )
        # No config source may self-certify behavioral qualification — not even
        # Survival Guide preference text. Qualification is runtime evidence only.
        if (
            "qualified_capabilities" in provided
            or "qualified" in provided
            or body_map.get("qualified_capabilities") is not None
            or body_map.get("qualified") is not None
        ):
            warn_sink.append(
                f"Ignoring config-declared qualified_capabilities for profile `{name}` "
                f"(source={source.value}); qualification requires runtime CapabilityRecord/"
                "LaneSpec evidence, not preference text"
            )
            provided.discard("qualified_capabilities")
            provided.discard("qualified")
        qualified_capabilities: tuple[str, ...] = ()
        session_raw = body_map.get("session_mode") or body_map.get("session-mode")
        if session_raw is None:
            session_mode = SessionMode.EPHEMERAL
        else:
            try:
                session_mode = SessionMode(str(session_raw).strip().lower().replace("-", "_"))
            except ValueError as exc:
                raise ValidationIssue(
                    "invalid_session_mode",
                    f"Unknown session mode `{session_raw}`",
                    path=f"{profile_path}.session_mode",
                ) from exc
        sharing_raw = body_map.get("context_sharing") or body_map.get("context-sharing")
        if sharing_raw is None:
            context_sharing = ContextSharingPolicy.INDEPENDENT
        else:
            try:
                context_sharing = ContextSharingPolicy(
                    str(sharing_raw).strip().lower().replace("-", "_")
                )
            except ValueError as exc:
                raise ValidationIssue(
                    "invalid_context_sharing",
                    f"Unknown context sharing `{sharing_raw}`",
                    path=f"{profile_path}.context_sharing",
                ) from exc
        # When IO fields are absent, use the resolved adapter's canonical pair.
        from .adapters import ADAPTER_CONTRACT_PAIRS

        adapter_pair = ADAPTER_CONTRACT_PAIRS.get(
            resolved_adapter, ("json-stdio", "custom-json-envelope")
        )
        if "input_contract" not in provided and "input" not in body_map:
            input_contract = adapter_pair[0]
        else:
            input_contract = str(
                body_map.get("input_contract") or body_map.get("input") or adapter_pair[0]
            ).strip()
        if "output_contract" not in provided and "output" not in body_map:
            output_contract = adapter_pair[1]
        else:
            output_contract = str(
                body_map.get("output_contract") or body_map.get("output") or adapter_pair[1]
            ).strip()
            if output_contract == "json-role-report":
                output_contract = adapter_pair[1]
        if "enabled" not in provided:
            enabled = True
        parsed[name] = HarnessProfile(
            name=name,
            adapter=resolved_adapter,
            executable=executable,
            notes=notes,
            session_mode=session_mode,
            context_sharing=context_sharing,
            enabled=enabled,
            requested_model=requested_model,
            extra_args=extra_args,
            env_grants=env_grants,
            input_contract=input_contract,
            output_contract=output_contract,
            capabilities=capabilities,
            qualified_capabilities=qualified_capabilities,
            provided_fields=tuple(sorted(provided)),
        )
    return parsed


def _extract_roles_and_profiles(
    data: Mapping[str, Any],
    *,
    source: ConfigSource,
    root_path: str,
    warnings: list[str] | None = None,
) -> tuple[dict[str, RoleRoute], dict[str, HarnessProfile]]:
    """Extract roles/profiles from a config-shaped mapping."""
    roles: dict[str, RoleRoute] = {}
    profiles: dict[str, HarnessProfile] = {}
    warn_sink = warnings if warnings is not None else []

    # TOML style: [profiles] / [roles]
    if "profiles" in data:
        profiles.update(
            _parse_profiles(
                data["profiles"],
                source=source,
                path=f"{root_path}.profiles",
                existing=profiles,
                warnings=warn_sink,
            )
        )
    if "roles" in data:
        role_data = _as_mapping(data["roles"], path=f"{root_path}.roles")
        for role_name, body in role_data.items():
            route = _parse_role_override(
                role_name,
                body,
                source=source,
                path=f"{root_path}.roles.{role_name}",
            )
            roles[route.role.value] = route

    # Survival guide style nested under model-routing / model_routing
    routing = data.get("model-routing") or data.get("model_routing") or {}
    if routing:
        routing_map = _as_mapping(routing, path=f"{root_path}.model_routing")
        if "profiles" in routing_map:
            profiles.update(
                _parse_profiles(
                    routing_map["profiles"],
                    source=source,
                    path=f"{root_path}.model_routing.profiles",
                    existing=profiles,
                    warnings=warn_sink,
                )
            )
        phases = routing_map.get("phases") or routing_map.get("roles") or {}
        phase_map = _as_mapping(phases, path=f"{root_path}.model_routing.phases")
        for role_name, body in phase_map.items():
            route = _parse_role_override(
                role_name,
                body,
                source=source,
                path=f"{root_path}.model_routing.phases.{role_name}",
            )
            # Global required only applies from Survival Guide when role omits required.
            if (
                source == ConfigSource.SURVIVAL_GUIDE
                and isinstance(body, Mapping)
                and "required" not in body
                and "required" in routing_map
            ):
                route = RoleRoute(
                    role=route.role,
                    profile=route.profile,
                    required=_as_bool(
                        routing_map.get("required"),
                        path=f"{root_path}.model_routing.required",
                    ),
                    fallback_chain=route.fallback_chain,
                    source=route.source,
                    session_mode=route.session_mode,
                    notes=route.notes,
                )
            roles[route.role.value] = route

    # config.json style: top-level model_routing.phases
    if "model_routing" in data and "phases" not in (data.get("model_routing") or {}):
        # Already handled above via model_routing key.
        pass

    return roles, profiles


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationIssue(
            "read_error",
            f"Unable to read config JSON at `{path}`",
            path=str(path),
            hint=str(exc),
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationIssue(
            "invalid_json",
            f"Invalid JSON in `{path}`: {exc.msg}",
            path=str(path),
            hint=f"line {exc.lineno} column {exc.colno}",
        ) from exc
    if not isinstance(data, dict):
        raise ValidationIssue(
            "invalid_type",
            f"Config JSON root must be an object in `{path}`",
            path=str(path),
        )
    return data


def load_toml_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationIssue(
            "read_error",
            f"Unable to read models TOML at `{path}`",
            path=str(path),
            hint=str(exc),
        ) from exc
    try:
        data = load_toml_text(raw.decode("utf-8"))
    except Exception as exc:
        raise ValidationIssue(
            "invalid_toml",
            f"Invalid TOML in `{path}`: {exc}",
            path=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ValidationIssue(
            "invalid_type",
            f"TOML root must be a table in `{path}`",
            path=str(path),
        )
    return data


def _merge_route(
    current: RoleRoute | None,
    incoming: RoleRoute,
) -> RoleRoute:
    if current is None:
        return incoming
    if SOURCE_RANK[incoming.source] >= SOURCE_RANK[current.source]:
        return incoming
    return current


def _merge_profile_fields(
    base: HarnessProfile,
    overlay: HarnessProfile,
    *,
    source: ConfigSource,
) -> HarnessProfile:
    """Field-presence-aware merge: only explicitly provided overlay fields win.

    Explicit empty lists clear base values. Explicit EPHEMERAL/INDEPENDENT reset
    lower values. Absent fields preserve base (including disabled/executable).
    """
    provided = set(overlay.provided_fields)

    def take(field: str, overlay_value: Any, base_value: Any) -> Any:
        return overlay_value if field in provided else base_value

    adapter = take("adapter", overlay.adapter, base.adapter)
    executable = take("executable", overlay.executable, base.executable)
    notes = take("notes", overlay.notes, base.notes) if "notes" in provided else (
        overlay.notes or base.notes
    )
    enabled = take("enabled", overlay.enabled, base.enabled)
    requested_model = take("requested_model", overlay.requested_model, base.requested_model)
    # model alias already mapped into provided requested_model
    if "model" in provided and "requested_model" not in provided:
        requested_model = overlay.requested_model
    extra_args = take("extra_args", overlay.extra_args, base.extra_args)
    env_grants = take("env_grants", overlay.env_grants, base.env_grants)
    capabilities = take("capabilities", overlay.capabilities, base.capabilities)
    # Qualification never merges from config overlays — runtime evidence only.
    qualified: tuple[str, ...] = ()
    input_contract = take("input_contract", overlay.input_contract, base.input_contract)
    output_contract = take("output_contract", overlay.output_contract, base.output_contract)
    session_mode = take("session_mode", overlay.session_mode, base.session_mode)
    context_sharing = take("context_sharing", overlay.context_sharing, base.context_sharing)

    merged_provided = tuple(sorted(set(base.provided_fields) | provided))
    return HarnessProfile(
        name=overlay.name or base.name,
        adapter=adapter or base.adapter,
        executable=executable,
        notes=notes or f"merged from {source.value}",
        session_mode=session_mode,
        context_sharing=context_sharing,
        enabled=enabled,
        requested_model=requested_model,
        extra_args=tuple(extra_args),
        env_grants=tuple(env_grants),
        input_contract=input_contract,
        output_contract=output_contract,
        capabilities=tuple(capabilities),
        qualified_capabilities=tuple(qualified),
        provided_fields=merged_provided,
    )


def resolve_config(
    *,
    survival_guide: Mapping[str, Any] | None = None,
    models_toml: Mapping[str, Any] | None = None,
    models_toml_path: Path | None = None,
    user_config: Mapping[str, Any] | None = None,
    user_config_path: Path | None = None,
    repo_root: Path | None = None,
) -> ResolvedConfig:
    """Resolve role routes with provenance.

    Callers may pass already-parsed mappings (tests) or filesystem paths.
    """
    resolved = ResolvedConfig(profiles=default_profiles())
    roles = native_defaults()
    resolved.sources_consulted.append(ConfigSource.NATIVE_DEFAULT.value)

    # Load filesystem sources when paths are provided.
    if user_config is None and user_config_path is not None and user_config_path.is_file():
        user_config = load_json_file(user_config_path)
    if models_toml is None and models_toml_path is not None and models_toml_path.is_file():
        models_toml = load_toml_file(models_toml_path)

    if repo_root is not None:
        default_toml = repo_root / ".elves" / "models.toml"
        if models_toml is None and models_toml_path is None and default_toml.is_file():
            models_toml = load_toml_file(default_toml)
            models_toml_path = default_toml
        default_json = repo_root / "config.json"
        if user_config is None and user_config_path is None and default_json.is_file():
            user_config = load_json_file(default_json)
            user_config_path = default_json

    layers: list[tuple[ConfigSource, Mapping[str, Any] | None, str]] = [
        (ConfigSource.USER_CONFIG_JSON, user_config, "user_config"),
        (ConfigSource.LOCAL_MODELS_TOML, models_toml, "models_toml"),
        (ConfigSource.SURVIVAL_GUIDE, survival_guide, "survival_guide"),
    ]

    try:
        for source, payload, label in layers:
            if not payload:
                continue
            resolved.sources_consulted.append(source.value)
            # Routing enablement: explicit false disables all external launches.
            routing = payload.get("model-routing") or payload.get("model_routing") or {}
            if isinstance(routing, Mapping) and "enabled" in routing:
                enabled_flag = _as_bool(
                    routing.get("enabled"),
                    path=f"{label}.model_routing.enabled",
                    default=True,
                )
                # Higher-precedence layers overwrite (layers iterate low→high).
                resolved.external_routing_enabled = enabled_flag
            layer_roles, layer_profiles = _extract_roles_and_profiles(
                payload,
                source=source,
                root_path=label,
                warnings=resolved.warnings,
            )
            for name, profile in layer_profiles.items():
                if name in resolved.profiles:
                    resolved.profiles[name] = _merge_profile_fields(
                        resolved.profiles[name],
                        profile,
                        source=source,
                    )
                else:
                    resolved.profiles[name] = profile
            for role_name, route in layer_roles.items():
                roles[role_name] = _merge_route(roles.get(role_name), route)

        if not resolved.external_routing_enabled:
            # Disabled external routing: every role resolves host-native; no launches.
            for role in DEFAULT_ROLES:
                roles[role.value] = RoleRoute(
                    role=role,
                    profile=NATIVE_PROFILE_NAME,
                    required=False,
                    fallback_chain=(),
                    source=ConfigSource.NATIVE_DEFAULT,
                    session_mode=SessionMode.EPHEMERAL,
                    notes="external routing disabled; host-native only",
                )
            resolved.warnings.append(
                "external_routing_enabled=false; all roles forced to host-native"
            )

        # Validate profiles referenced by routes exist; required unavailable blocks.
        for role_name, route in roles.items():
            profile_name = route.profile
            if profile_name not in resolved.profiles:
                # Allow bare built-in adapter names as profiles.
                if profile_name in default_profiles():
                    resolved.profiles[profile_name] = default_profiles()[profile_name]
                else:
                    issue = ValidationIssue(
                        "unknown_profile",
                        f"Role `{role_name}` references unknown profile `{profile_name}`",
                        path=f"roles.{role_name}.profile",
                        hint="Define the profile or map the role to a built-in adapter name",
                    )
                    if route.required:
                        resolved.issues.append(issue)
                    else:
                        # Optional: fall back to native without crashing.
                        resolved.warnings.append(issue.message)
                        roles[role_name] = RoleRoute(
                            role=route.role,
                            profile=NATIVE_PROFILE_NAME,
                            required=False,
                            fallback_chain=route.fallback_chain,
                            source=route.source,
                            session_mode=route.session_mode,
                            notes=f"Fell back to host-native: {issue.message}",
                        )
                    continue

            # Validate fallback chain profiles.
            cleaned_fallback: list[FallbackEntry] = []
            for entry in route.fallback_chain:
                if entry.profile not in resolved.profiles and entry.profile not in default_profiles():
                    msg = (
                        f"Role `{role_name}` fallback references unknown profile "
                        f"`{entry.profile}`"
                    )
                    if route.required:
                        resolved.issues.append(
                            ValidationIssue(
                                "unknown_fallback_profile",
                                msg,
                                path=f"roles.{role_name}.fallback_chain",
                            )
                        )
                    else:
                        resolved.warnings.append(msg)
                    continue
                if entry.profile not in resolved.profiles:
                    resolved.profiles[entry.profile] = default_profiles()[entry.profile]
                cleaned_fallback.append(entry)
            if cleaned_fallback != list(route.fallback_chain):
                roles[role_name] = RoleRoute(
                    role=route.role,
                    profile=roles[role_name].profile,
                    required=route.required,
                    fallback_chain=tuple(cleaned_fallback),
                    source=route.source,
                    session_mode=route.session_mode,
                    notes=route.notes,
                )

        # Deterministic role order in output.
        ordered: dict[str, RoleRoute] = {}
        for role in DEFAULT_ROLES:
            if role.value in roles:
                ordered[role.value] = roles[role.value]
        for role_name, route in roles.items():
            if role_name not in ordered:
                ordered[role_name] = route
        resolved.roles = ordered
    except ValidationIssue as issue:
        resolved.issues.append(issue)

    return resolved


def resolve_from_repo(
    repo_root: Path,
    *,
    survival_guide: Mapping[str, Any] | None = None,
) -> ResolvedConfig:
    """Resolve using the standard on-disk locations under repo_root."""
    return resolve_config(
        survival_guide=survival_guide,
        models_toml_path=repo_root / ".elves" / "models.toml",
        user_config_path=repo_root / "config.json",
        repo_root=repo_root,
    )


def models_toml_is_local_only(repo_root: Path) -> dict[str, Any]:
    """Return metadata proving local TOML is ignored/untracked project state."""
    path = repo_root / ".elves" / "models.toml"
    gitignore = repo_root / ".gitignore"
    ignored_by_gitignore = False
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        ignored_by_gitignore = any(
            line.strip() in {".elves/", ".elves/**", ".elves/models.toml"}
            for line in text.splitlines()
        ) or ".elves/" in text
    return {
        "path": str(path.as_posix()),
        "exists": path.is_file(),
        "ignored_by_gitignore": ignored_by_gitignore,
        "committed": False,
        "note": (
            "`.elves/models.toml` is local checkout preference only; "
            "never stage it. Tracked schema lives in references/models.toml.example."
        ),
    }


def effective_attempts_for_role(
    resolved: ResolvedConfig,
    role_name: str,
) -> tuple[EffectiveAttempt, ...]:
    """Return ordered primary+fallback attempts for a resolved role (no field loss)."""
    route = resolved.roles.get(role_name)
    if route is None:
        raise ValidationIssue(
            "unknown_role",
            f"Role `{role_name}` is not in the resolved routing table",
            path=f"roles.{role_name}",
        )
    return build_effective_attempts(route, resolved.profiles)


def lanes_from_resolved(
    resolved: ResolvedConfig,
    *,
    role_names: Sequence[str] | None = None,
    timeout_seconds: float = 30.0,
    use_resolved_routes: bool = True,
) -> list[Any]:
    """Build dispatch LaneSpec list from resolved config without field loss.

    When ``use_resolved_routes`` is False, every lens stays host-native (CLI smoke).
    Host-native still requires injected evidence at execution time for a vote.
    """
    if role_names is None:
        role_names = [r.value for r in DEFAULT_ROLES if r.value in resolved.roles]

    lanes: list[LaneSpec] = []
    for index, role in enumerate(role_names):
        role = role.strip()
        if not role:
            continue

        # Prefer an exact role match; free lenses may share review/planning routes.
        route = (
            resolved.roles.get(role)
            or resolved.roles.get(role.replace("-", "_"))
            or resolved.roles.get("review")
            or resolved.roles.get("planning")
        )

        # Survival-guide required routes cannot be erased by use_resolved_routes=false.
        force_resolved = bool(
            route
            and route.required
            and route.source == ConfigSource.SURVIVAL_GUIDE
        )

        if (
            (not use_resolved_routes and not force_resolved)
            or not resolved.external_routing_enabled
        ):
            lanes.append(
                LaneSpec(
                    lane_id=f"{role}-{index}",
                    role=role,
                    adapter=NATIVE_PROFILE_NAME,
                    profile=NATIVE_PROFILE_NAME,
                    requested_model=None,
                    required=False,
                    timeout_seconds=timeout_seconds,
                )
            )
            continue

        if route is None or route.profile not in resolved.profiles:
            lanes.append(
                LaneSpec(
                    lane_id=f"{role}-{index}",
                    role=role,
                    adapter=NATIVE_PROFILE_NAME,
                    profile=NATIVE_PROFILE_NAME,
                    requested_model=None,
                    required=bool(route.required) if route else False,
                    timeout_seconds=timeout_seconds,
                )
            )
            continue

        attempts = build_effective_attempts(route, resolved.profiles)
        primary = attempts[0]
        lanes.append(
            LaneSpec(
                lane_id=f"{role}-{index}",
                role=role,
                adapter=primary.adapter,
                profile=primary.profile,
                requested_model=primary.requested_model,
                executable=primary.executable,
                required=route.required and route.source == ConfigSource.SURVIVAL_GUIDE,
                timeout_seconds=timeout_seconds,
                extra_args=primary.extra_args,
                env_grants=primary.env_grants,
                attempts=attempts,
            )
        )
    return lanes
