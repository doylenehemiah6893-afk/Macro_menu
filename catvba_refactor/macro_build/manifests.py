import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .canonical import canonical_json_bytes, sha256_bytes
from .errors import ConfigError
from .model import Diagnostic, ValidationReport
from .runtime_contract import canonical_runtime_id


_MANIFEST_NAMES = ("components", "packages", "project", "tools")
_FORBIDDEN_LICENSE_RESULTS = {"pass", "passed", "verified"}


@dataclass(frozen=True)
class ManifestSet:
    project: dict[str, Any]
    components: dict[str, Any]
    packages: dict[str, Any]
    tools: dict[str, Any]
    digest: str
    report: ValidationReport


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"DUPLICATE_JSON_KEY: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(
            f"JSON_READ_ERROR: {path.name}: {type(exc).__name__}"
        ) from exc

    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except ConfigError:
        raise
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"INVALID_JSON: {path.name}:{exc.lineno}:{exc.colno}"
        ) from exc


def _pointer(filename: str, parts: tuple[Any, ...]) -> str:
    if not parts:
        return f"{filename}#"
    encoded = "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )
    return f"{filename}#/{encoded}"


def _contains_forbidden_license_claim(
    key: str, value: Any, *, license_context: bool = False
) -> bool:
    normalized_key = key.casefold().replace("-", "_")
    in_license_context = license_context or "license" in normalized_key

    if in_license_context:
        if isinstance(value, str):
            result = value.strip().casefold().replace("_", "-")
            if result in _FORBIDDEN_LICENSE_RESULTS:
                return True
        if (
            value is True
            and ("verified" in normalized_key or "pass" in normalized_key)
        ):
            return True

    if isinstance(value, dict):
        return any(
            _contains_forbidden_license_claim(
                str(nested_key),
                nested_value,
                license_context=in_license_context,
            )
            for nested_key, nested_value in value.items()
        )
    if isinstance(value, list):
        return any(
            _contains_forbidden_license_claim(
                key, item, license_context=in_license_context
            )
            for item in value
        )
    return False


def _schema_message(error: ValidationError) -> str:
    if error.validator == "type":
        expected = error.validator_value
        if isinstance(expected, list):
            expected_text = ", ".join(str(value) for value in expected)
        else:
            expected_text = str(expected)
        return f"expected type: {expected_text}"
    if error.validator == "pattern":
        return f"value does not match required pattern: {error.validator_value}"
    if error.validator == "const":
        return f"value must equal {error.validator_value!r}"
    if error.validator == "enum":
        values = ", ".join(repr(value) for value in error.validator_value)
        return f"value must be one of: {values}"
    if error.validator == "uniqueItems":
        return "array entries must be unique"
    if error.validator == "minItems":
        return f"array requires at least {error.validator_value} entries"
    if error.validator == "maxItems":
        return f"array permits at most {error.validator_value} entries"
    if error.validator == "not":
        return "field combination is forbidden"
    return error.message


def _schema_diagnostics(
    filename: str, document: Any, schema: dict[str, Any]
) -> list[Diagnostic]:
    validator = Draft202012Validator(schema)
    diagnostics: list[Diagnostic] = []

    for error in validator.iter_errors(document):
        parts = tuple(error.absolute_path)
        if error.validator == "additionalProperties" and isinstance(
            error.instance, dict
        ):
            properties = error.schema.get("properties", {})
            allowed = set(properties) if isinstance(properties, dict) else set()
            extra_keys = sorted(set(error.instance) - allowed)
            if extra_keys:
                for key in extra_keys:
                    value = error.instance[key]
                    forbidden_license = _contains_forbidden_license_claim(key, value)
                    diagnostics.append(
                        Diagnostic(
                            code=(
                                "LICENSE_STATUS_FORBIDDEN"
                                if forbidden_license
                                else "SCHEMA_UNKNOWN_FIELD"
                            ),
                            path=_pointer(filename, parts + (key,)),
                            message=(
                                "manifest cannot claim a verified or passed "
                                "license result"
                                if forbidden_license
                                else f"unknown field: {key}"
                            ),
                        )
                    )
                continue

        code = (
            "SCHEMA_REQUIRED_FIELD"
            if error.validator == "required"
            else "SCHEMA_VALIDATION"
        )
        diagnostics.append(
            Diagnostic(
                code=code,
                path=_pointer(filename, parts),
                message=_schema_message(error),
            )
        )

    return diagnostics


def _records(document: Any, key: str) -> list[tuple[int, dict[str, Any]]]:
    if not isinstance(document, dict):
        return []
    value = document.get(key)
    if not isinstance(value, list):
        return []
    return [
        (index, item) for index, item in enumerate(value) if isinstance(item, dict)
    ]


def _index_records(
    records: list[tuple[int, dict[str, Any]]],
    *,
    filename: str,
    collection: str,
    id_field: str,
    kind: str,
) -> tuple[dict[str, dict[str, Any]], list[Diagnostic]]:
    indexed: dict[str, dict[str, Any]] = {}
    diagnostics: list[Diagnostic] = []
    for index, record in records:
        record_id = record.get(id_field)
        if not isinstance(record_id, str):
            continue
        if record_id in indexed:
            diagnostics.append(
                Diagnostic(
                    code="DUPLICATE_ID",
                    path=_pointer(filename, (collection, index, id_field)),
                    message=f"duplicate {kind} ID: {record_id}",
                )
            )
            continue
        indexed[record_id] = record
    return indexed, diagnostics


def _member_roles(value: Any) -> Counter[str] | None:
    if not isinstance(value, list):
        return None
    roles: list[str] = []
    for member in value:
        if not isinstance(member, dict) or not isinstance(member.get("role"), str):
            return None
        roles.append(member["role"])
    return Counter(roles)


def _binding_diagnostics(
    component: dict[str, Any], index: int
) -> list[Diagnostic]:
    component_type = component.get("component_type")
    if component_type not in {"standard_module", "class_module", "user_form"}:
        return []

    diagnostics: list[Diagnostic] = []
    is_form = component_type == "user_form"
    expected = Counter({"frm": 1, "frx": 1}) if is_form else Counter({"source": 1})
    selected_roles = _member_roles(component.get("members"))
    binding_code = "FORM_BINDING_INCOMPLETE" if is_form else "MEMBER_BINDING_INVALID"
    expected_text = "one frm and one frx" if is_form else "one source"

    if selected_roles != expected:
        diagnostics.append(
            Diagnostic(
                code=binding_code,
                path=_pointer("components.json", ("components", index, "members")),
                message=f"{component_type} requires exactly {expected_text} member binding",
            )
        )

    origin = component.get("origin")
    if origin == "override":
        base_roles = _member_roles(component.get("base_members"))
        if base_roles != expected:
            diagnostics.append(
                Diagnostic(
                    code=binding_code,
                    path=_pointer(
                        "components.json", ("components", index, "base_members")
                    ),
                    message=(
                        f"override {component_type} requires exactly {expected_text} "
                        "base member binding"
                    ),
                )
            )
        if selected_roles is not None and base_roles is not None:
            if selected_roles != base_roles:
                diagnostics.append(
                    Diagnostic(
                        code="MEMBER_BINDING_MISMATCH",
                        path=_pointer(
                            "components.json", ("components", index, "base_members")
                        ),
                        message="override base member roles must mirror selected roles",
                    )
                )
    elif "base_members" in component:
        diagnostics.append(
            Diagnostic(
                code="BASE_MEMBERS_FORBIDDEN",
                path=_pointer(
                    "components.json", ("components", index, "base_members")
                ),
                message="base_members is allowed only for override components",
            )
        )

    return diagnostics


def _canonical_id_diagnostics(
    records: list[tuple[int, dict[str, Any]]],
    *,
    field: str,
    kind: str,
) -> list[Diagnostic]:
    originals_by_canonical: dict[str, set[str]] = {}
    for _, record in records:
        value = record.get(field)
        if not isinstance(value, str):
            continue
        try:
            canonical = canonical_runtime_id(value)
        except (TypeError, ValueError):
            continue
        originals_by_canonical.setdefault(canonical, set()).add(value)

    diagnostics: list[Diagnostic] = []
    for canonical, originals in sorted(originals_by_canonical.items()):
        if len(originals) < 2:
            continue
        rendered = ", ".join(repr(value) for value in sorted(originals))
        diagnostics.append(
            Diagnostic(
                code="CANONICAL_ID_COLLISION",
                path="tools.json#/tools",
                message=(
                    f"canonical {kind} ID collision for {canonical}: {rendered}"
                ),
            )
        )
    return diagnostics


def _group_caption_diagnostics(
    records: list[tuple[int, dict[str, Any]]],
) -> list[Diagnostic]:
    captions_by_group: dict[str, set[str]] = {}
    for _, record in records:
        group_id = record.get("group_id")
        group_caption = record.get("group_caption")
        if isinstance(group_id, str) and isinstance(group_caption, str):
            captions_by_group.setdefault(group_id, set()).add(group_caption)

    diagnostics: list[Diagnostic] = []
    for group_id, captions in sorted(captions_by_group.items()):
        if len(captions) < 2:
            continue
        rendered = ", ".join(repr(value) for value in sorted(captions))
        diagnostics.append(
            Diagnostic(
                code="GROUP_CAPTION_CONFLICT",
                path="tools.json#/tools",
                message=f"group {group_id} has conflicting captions: {rendered}",
            )
        )
    return diagnostics


def _cross_file_diagnostics(documents: dict[str, Any]) -> list[Diagnostic]:
    component_records = _records(documents["components"], "components")
    root_records = _records(documents["components"], "source_roots")
    package_records = _records(documents["packages"], "packages")
    tool_records = _records(documents["tools"], "tools")

    roots, root_diagnostics = _index_records(
        root_records,
        filename="components.json",
        collection="source_roots",
        id_field="root_id",
        kind="source root",
    )
    sources, source_diagnostics = _index_records(
        component_records,
        filename="components.json",
        collection="components",
        id_field="source_id",
        kind="source",
    )
    packages, package_diagnostics = _index_records(
        package_records,
        filename="packages.json",
        collection="packages",
        id_field="package_id",
        kind="package",
    )
    tools, tool_diagnostics = _index_records(
        tool_records,
        filename="tools.json",
        collection="tools",
        id_field="tool_id",
        kind="tool",
    )
    # Keep the exact-ID dictionaries materialized before resolving references.
    _ = roots, sources, tools

    diagnostics = [
        *root_diagnostics,
        *source_diagnostics,
        *package_diagnostics,
        *tool_diagnostics,
    ]
    diagnostics.extend(
        _canonical_id_diagnostics(tool_records, field="tool_id", kind="tool")
    )
    diagnostics.extend(
        _canonical_id_diagnostics(tool_records, field="group_id", kind="group")
    )
    diagnostics.extend(_group_caption_diagnostics(tool_records))

    for index, component in component_records:
        package_id = component.get("package_id")
        disposition = component.get("disposition")
        package_path = _pointer(
            "components.json", ("components", index, "package_id")
        )
        if disposition == "candidate" and not isinstance(package_id, str):
            diagnostics.append(
                Diagnostic(
                    code="PACKAGE_REQUIRED",
                    path=package_path,
                    message="candidate component requires a package_id",
                )
            )
        elif isinstance(package_id, str) and package_id not in packages:
            diagnostics.append(
                Diagnostic(
                    code="UNKNOWN_PACKAGE",
                    path=package_path,
                    message=f"unknown package: {package_id}",
                )
            )
        diagnostics.extend(_binding_diagnostics(component, index))

    for index, tool in tool_records:
        package_id = tool.get("package_id")
        if isinstance(package_id, str) and package_id not in packages:
            diagnostics.append(
                Diagnostic(
                    code="UNKNOWN_PACKAGE",
                    path=_pointer("tools.json", ("tools", index, "package_id")),
                    message=f"unknown package: {package_id}",
                )
            )

    return diagnostics


def load_and_validate_config(config_dir: Path, schema_dir: Path) -> ManifestSet:
    documents: dict[str, Any] = {}
    schemas: dict[str, dict[str, Any]] = {}

    for name in _MANIFEST_NAMES:
        documents[name] = _read_json(config_dir / f"{name}.json")
        schema = _read_json(schema_dir / f"{name}.schema.json")
        if not isinstance(schema, dict):
            raise ConfigError(f"INVALID_SCHEMA: {name}.schema.json")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ConfigError(f"INVALID_SCHEMA: {name}.schema.json") from exc
        schemas[name] = schema

    diagnostics: list[Diagnostic] = []
    for name in _MANIFEST_NAMES:
        diagnostics.extend(
            _schema_diagnostics(f"{name}.json", documents[name], schemas[name])
        )
    diagnostics.extend(_cross_file_diagnostics(documents))
    report = ValidationReport(tuple(diagnostics)).sorted()

    try:
        canonical_documents = b"".join(
            canonical_json_bytes(documents[name]) for name in _MANIFEST_NAMES
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("NON_CANONICAL_JSON: manifest values") from exc

    return ManifestSet(
        project=cast(dict[str, Any], documents["project"]),
        components=cast(dict[str, Any], documents["components"]),
        packages=cast(dict[str, Any], documents["packages"]),
        tools=cast(dict[str, Any], documents["tools"]),
        digest=sha256_bytes(canonical_documents),
        report=report,
    )
