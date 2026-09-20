"""Bounded runtime adapter over the canonical installed TypeSafe broker."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import importlib.metadata
import importlib.util
import math
import secrets
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

if __package__:
    from ._build_identity import ABI as NATIVE_BROKER_ABI, BUILD_SHA256 as NATIVE_BUILD_SHA256
    from .client import AsyncTypeSafeClient, ClientError, _validated_optional_choice_questions
    from .limits import LimitsError, ValidatedRequest, preflight_request
    from .questions import HOOK_TIMEOUT_SECONDS, TOOL_TIMEOUT_SECONDS, USEFUL_TOOL_SECONDS
else:  # pragma: no cover - flat plugin smoke import
    from _build_identity import ABI as NATIVE_BROKER_ABI, BUILD_SHA256 as NATIVE_BUILD_SHA256
    from client import AsyncTypeSafeClient, ClientError, _validated_optional_choice_questions
    from limits import LimitsError, ValidatedRequest, preflight_request
    from questions import HOOK_TIMEOUT_SECONDS, TOOL_TIMEOUT_SECONDS, USEFUL_TOOL_SECONDS

BROKER_ABI = NATIVE_BROKER_ABI
BROKER_BUILD_SHA256 = NATIVE_BUILD_SHA256


def _valid_api_key(value: Any) -> bool:
    if type(value) is not str or not value.strip() or len(value) > 4_096:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def _timeout_value(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


class RuntimeUnavailable(RuntimeError):
    """The canonical runtime cannot be used safely in this process."""


@dataclass(frozen=True)
class _SafeFailure:
    code: str


class _UnavailableFactory:
    def __call__(self, **_: Any) -> Any:
        raise RuntimeUnavailable


def _bounded_file(path: Path, cap: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise RuntimeUnavailable
        data = path.read_bytes()
    except (OSError, RuntimeUnavailable):
        raise RuntimeUnavailable from None
    if len(data) > cap:
        raise RuntimeUnavailable
    return data


def _identity_literals(path: Path) -> dict[str, str]:
    try:
        tree = ast.parse(_bounded_file(path, 4_096).decode("utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, RuntimeUnavailable):
        raise RuntimeUnavailable from None
    values: dict[str, str] = {}
    for index, node in enumerate(tree.body):
        is_docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is str
        )
        if is_docstring:
            continue
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise RuntimeUnavailable
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"ABI", "BUILD_SHA256"}:
            raise RuntimeUnavailable
        if target.id in values or not isinstance(node.value, ast.Constant) or type(node.value.value) is not str:
            raise RuntimeUnavailable
        values[target.id] = node.value.value
    if set(values) != {"ABI", "BUILD_SHA256"}:
        raise RuntimeUnavailable
    return values


def _source_digest(root: Path) -> str:
    payload = bytearray()
    for relative in ("__init__.py", "core.py"):
        data = _bounded_file(root / relative, 262_144)
        payload.extend(relative.encode("utf-8"))
        payload.extend(b"\0")
        payload.extend(str(len(data)).encode("ascii"))
        payload.extend(b"\0")
        payload.extend(data)
    return hashlib.sha256(payload).hexdigest()


def _distribution_owns(root: Path) -> bool:
    try:
        distribution = importlib.metadata.distribution("hermes-typesafe")
        files = distribution.files
    except importlib.metadata.PackageNotFoundError:
        return False
    if files is None:
        return False
    required = {
        "hermes_typesafe_broker/__init__.py",
        "hermes_typesafe_broker/core.py",
        "hermes_typesafe_broker/_build_identity.py",
    }
    normalized = [str(path).replace("\\", "/") for path in files]
    if any(normalized.count(path) != 1 for path in required):
        return False
    if not required.issubset(normalized):
        return False
    try:
        package_path = Path(str(distribution.locate_file("hermes_typesafe_broker")))
        if package_path.is_symlink() or not package_path.is_dir() or package_path.resolve() != root.resolve():
            return False
        for relative in required:
            record_path = Path(relative)
            expected = root / record_path.relative_to("hermes_typesafe_broker")
            located = Path(str(distribution.locate_file(record_path)))
            if expected.is_symlink() or located.is_symlink() or not expected.is_file() or not located.is_file():
                return False
            if expected.resolve() != located.resolve():
                return False
    except (OSError, ValueError):
        return False
    return True


def _load_broker() -> ModuleType:
    """Verify the installed same-distribution broker before importing its core."""

    try:
        spec = importlib.util.find_spec("hermes_typesafe_broker")
    except Exception as error:
        del error
        raise RuntimeUnavailable from None
    if spec is None or not spec.submodule_search_locations or len(spec.submodule_search_locations) != 1:
        raise RuntimeUnavailable
    root = Path(next(iter(spec.submodule_search_locations)))
    if root.is_symlink() or not root.is_dir():
        raise RuntimeUnavailable
    origin = Path(spec.origin) if isinstance(spec.origin, str) else None
    if origin is None or origin.is_symlink() or origin.resolve() != (root / "__init__.py").resolve():
        raise RuntimeUnavailable
    if not _distribution_owns(root):
        raise RuntimeUnavailable
    for module_name, expected in (
        ("hermes_typesafe_broker", root / "__init__.py"),
        ("hermes_typesafe_broker._build_identity", root / "_build_identity.py"),
        ("hermes_typesafe_broker.core", root / "core.py"),
    ):
        loaded = sys.modules.get(module_name)
        if loaded is None:
            continue
        origin = getattr(loaded, "__file__", None)
        origin_path = Path(origin) if isinstance(origin, str) else None
        if origin_path is None or origin_path.is_symlink() or Path(expected).is_symlink() or origin_path.resolve() != expected.resolve():
            raise RuntimeUnavailable
    generated = _identity_literals(root / "_build_identity.py")
    if (
        generated.get("ABI") != BROKER_ABI
        or generated.get("BUILD_SHA256") != _source_digest(root)
        or generated.get("BUILD_SHA256") != BROKER_BUILD_SHA256
    ):
        raise RuntimeUnavailable
    try:
        broker = importlib.import_module("hermes_typesafe_broker.core")
    except Exception as error:
        del error
        raise RuntimeUnavailable from None
    if getattr(broker, "__name__", None) != "hermes_typesafe_broker.core":
        raise RuntimeUnavailable
    if getattr(broker, "ABI", None) != BROKER_ABI or getattr(broker, "BUILD_SHA256", None) != generated["BUILD_SHA256"]:
        raise RuntimeUnavailable
    return broker


def _effective_home() -> str | None:
    for module_name in ("hermes_constants", "agent"):
        try:
            module = importlib.import_module(module_name)
            getter = getattr(module, "get_hermes_home", None)
            if not callable(getter):
                continue
            value = getter()
            if value is None:
                return None
            return value if type(value) is str else str(value)
        except Exception:
            continue
    return None


def _main_interpreter() -> bool:
    try:
        import _xxsubinterpreters

        return _xxsubinterpreters.get_current() == _xxsubinterpreters.get_main()
    except Exception:
        return False


def _supported_runtime() -> bool:
    supported_version = sys.version_info[:2] in {(3, 10), (3, 11), (3, 12)}
    return sys.implementation.name == "cpython" and supported_version and _main_interpreter()


class TypeSafeRuntime:
    """A profile-local adapter with lazy canonical broker admission."""

    def __init__(
        self,
        *,
        settings: Mapping[str, Any] | None = None,
        home_identity: str | None = None,
        require_home_identity: bool = False,
        broker_loader: Callable[[], ModuleType] | None = None,
        client_factory: Callable[..., AsyncTypeSafeClient] | None = None,
    ) -> None:
        self.settings = {key: value for key, value in (settings or {}).items() if type(key) is str}
        self.home_identity = home_identity
        self._require_home_identity = require_home_identity
        self._broker_loader = broker_loader or _load_broker
        self._client_factory = client_factory or AsyncTypeSafeClient
        self._broker: ModuleType | None = None
        self._lease: Any = None
        self._closed = False
        self._lock = threading.Lock()

    def _available_home(self) -> bool:
        if not _main_interpreter():
            return False
        if self._require_home_identity and (type(self.home_identity) is not str or not self.home_identity):
            return False
        if self.home_identity is None:
            return True
        current = _effective_home()
        return current == self.home_identity

    def _lease_for_operation(self) -> tuple[ModuleType, Any] | None:
        self._lock.acquire()
        try:
            if self._closed or not self._available_home():
                return None
            if self._broker is None:
                try:
                    self._broker = self._broker_loader()
                except Exception:
                    self._closed = True
                    return None
            if self._lease is None:
                try:
                    self._lease = self._broker.acquire(
                        self._broker.ABI,
                        self._broker.BUILD_SHA256,
                        secrets.token_bytes(32),
                    )
                except Exception:
                    self._closed = True
                    return None
            if self._lease is None:
                return None
            return self._broker, self._lease
        finally:
            self._lock.release()

    def _validated(self, state: Any, questions: Any, model: str) -> ValidatedRequest:
        try:
            return preflight_request(state=state, questions=questions, model=model)
        except LimitsError as error:
            raise ClientError("payload_too_large" if error.code == "payload_too_large" else "invalid_input") from None

    def _submit(
        self,
        checked: ValidatedRequest,
        *,
        api_key: Any,
        deadline: float,
        optional_choice_questions: tuple[str, ...],
    ) -> tuple[ModuleType, Any, Any] | None:
        loaded = self._lease_for_operation()
        if loaded is None:
            return None
        broker, lease = loaded
        state = checked.state
        questions = checked.questions
        model = checked.model
        client_factory = self._client_factory

        async def work() -> dict[str, Any]:
            client_timeout = max(0.001, min(deadline - time.monotonic(), USEFUL_TOOL_SECONDS))
            client = client_factory(api_key=api_key, model=model, timeout=client_timeout)
            try:
                if optional_choice_questions:
                    return await client.system_one(
                        state,
                        questions,
                        optional_choice_questions=optional_choice_questions,
                    )
                return await client.system_one(state, questions)
            except ClientError as error:
                return _SafeFailure(error.code)  # type: ignore[return-value]

        operation = broker.try_submit(lease, deadline, work)
        return broker, operation, lease

    def execute_sync(
        self,
        *,
        state: Any,
        questions: Any,
        model: str,
        api_key: str | None,
        timeout: float = TOOL_TIMEOUT_SECONDS,
        optional_choice_questions: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        started = time.monotonic()
        if not _valid_api_key(api_key):
            raise ClientError("unavailable")
        requested_timeout = _timeout_value(timeout)
        if requested_timeout is None:
            raise ClientError("invalid_input")
        checked = self._validated(state, questions, model)
        optional_choice_questions = _validated_optional_choice_questions(
            checked.questions, optional_choice_questions
        )
        remaining = requested_timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ClientError("timeout")
        deadline = started + requested_timeout
        submitted = self._submit(
            checked,
            api_key=api_key,
            deadline=deadline,
            optional_choice_questions=optional_choice_questions,
        )
        if submitted is None or submitted[1] is None:
            raise ClientError("timeout" if time.monotonic() >= deadline else "unavailable")
        _, operation, _ = submitted
        remaining = max(0.0, deadline - time.monotonic())
        try:
            result = operation.result(timeout=remaining)
            if isinstance(result, _SafeFailure):
                raise ClientError(result.code)
            return result
        except TimeoutError:
            operation.cancel()
            raise ClientError("timeout") from None
        except Exception as error:
            name = type(error).__name__
            if name == "OperationUnavailable":
                raise ClientError("timeout" if time.monotonic() >= operation.deadline else "unavailable") from None
            if isinstance(error, ClientError):
                raise
            if time.monotonic() >= operation.deadline:
                raise ClientError("timeout") from None
            raise ClientError("provider_unavailable") from None

    async def execute_async(
        self,
        *,
        state: Any,
        questions: Any,
        model: str,
        api_key: str | None,
        timeout: float = TOOL_TIMEOUT_SECONDS,
        optional_choice_questions: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        started = time.monotonic()
        if not _valid_api_key(api_key):
            raise ClientError("unavailable")
        requested_timeout = _timeout_value(timeout)
        if requested_timeout is None:
            raise ClientError("invalid_input")
        checked = self._validated(state, questions, model)
        optional_choice_questions = _validated_optional_choice_questions(
            checked.questions, optional_choice_questions
        )
        remaining = requested_timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ClientError("timeout")
        deadline = started + requested_timeout
        submitted = self._submit(
            checked,
            api_key=api_key,
            deadline=deadline,
            optional_choice_questions=optional_choice_questions,
        )
        if submitted is None or submitted[1] is None:
            raise ClientError("timeout" if time.monotonic() >= deadline else "unavailable")
        _, operation, _ = submitted
        remaining = max(0.0, deadline - time.monotonic())
        future = asyncio.wrap_future(operation.future)
        try:
            result = await asyncio.wait_for(future, timeout=remaining)
            if isinstance(result, _SafeFailure):
                raise ClientError(result.code)
            return result
        except asyncio.TimeoutError:
            operation.cancel()
            raise ClientError("timeout") from None
        except Exception as error:
            if isinstance(error, ClientError):
                raise
            name = type(error).__name__
            if name == "OperationUnavailable":
                raise ClientError("timeout" if time.monotonic() >= operation.deadline else "unavailable") from None
            if time.monotonic() >= operation.deadline:
                raise ClientError("timeout") from None
            raise ClientError("provider_unavailable") from None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            broker, lease = self._broker, self._lease
            self._lease = None
        if broker is not None and lease is not None:
            try:
                broker.release(lease)
            except Exception:
                pass


def runtime_status() -> dict[str, str]:
    """Return static runtime support facts without importing SDK or starting work."""

    return {
        "status": "runtime_ready" if _supported_runtime() else "runtime_unavailable",
        "reason": "canonical installed broker and supported main interpreter required before operation",
    }


__all__ = [
    "HOOK_TIMEOUT_SECONDS",
    "TOOL_TIMEOUT_SECONDS",
    "TypeSafeRuntime",
    "RuntimeUnavailable",
    "runtime_status",
]
