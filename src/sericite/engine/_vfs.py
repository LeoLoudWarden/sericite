from __future__ import annotations

from ..accounting import AllocationPermit
from ..errors import SericiteError
from ..vfs import VFSAttachment, VirtualFileSystem
from ._model import VFSHandle
from ._values import _estimate_size


class _EngineVFS:
    def create_vfs(self) -> VFSHandle:
        self._reject_observation_reentry()
        self._flush_pending_events()
        return VFSHandle(self, VFSAttachment())

    def _vfs_attachment(self, handle: VFSHandle) -> VFSAttachment:
        self._reject_observation_reentry()
        if not isinstance(handle, VFSHandle):
            raise SericiteError("fs must be a VFS or None", kind="type_error")
        if handle._engine is not self:
            raise SericiteError(
                "VFS handle belongs to another engine", kind="internal_error"
            )
        if handle._consumed:
            raise SericiteError("VFS handle has been consumed", kind="runtime_error")
        if handle._attachment.owner_vm_id is not None:
            raise SericiteError("VFS is attached to a VM", kind="runtime_error")
        return handle._attachment

    def _detached_vfs(self, handle: VFSHandle) -> VirtualFileSystem:
        return self._vfs_attachment(handle).fs

    def _vfs_method_work(
        self,
        handle: VFSHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int:
        fs = self._detached_vfs(handle)
        if attr == "write_file":
            path = args[0] if args else kwargs.get("path")
            text = args[1] if len(args) > 1 else kwargs.get("text")
            return fs.write_work(path, text)
        if attr in ("rename_file", "rename_dir"):
            old_path = args[0] if args else kwargs.get("old_path")
            new_path = args[1] if len(args) > 1 else kwargs.get("new_path")
            work = fs.rename_work if attr == "rename_file" else fs.rename_dir_work
            return work(old_path, new_path)
        if attr in ("copy_file", "copy_dir"):
            source_path = args[0] if args else kwargs.get("source_path")
            destination_path = (
                args[1] if len(args) > 1 else kwargs.get("destination_path")
            )
            work = fs.copy_work if attr == "copy_file" else fs.copy_dir_work
            return work(source_path, destination_path)
        if attr == "list_dir":
            path = args[0] if args else kwargs.get("path")
            return fs.list_dir_work(path)
        if attr == "delete_dir":
            path = args[0] if args else kwargs.get("path")
            return fs.delete_dir_work(path)
        if attr in {"read_file", "delete_file", "make_dir", "path_exists"}:
            path = args[0] if args else kwargs.get("path")
            return fs.path_work(path)
        raise SericiteError(
            f"no work contract for VFS method '{attr}'", kind="internal_error"
        )

    def _vfs_method_allocation(
        self,
        handle: VFSHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int | AllocationPermit:
        context = kwargs["_caller_context"]
        fs = self._detached_vfs(handle)
        if attr in {"read_file", "list_dir", "path_exists"}:
            return 0
        if attr in {"delete_file", "delete_dir"}:
            self._meter(context).allocate(8)
            return 0
        estimates = {
            "write_file": fs.write_allocation,
            "rename_file": fs.rename_allocation,
            "rename_dir": fs.rename_dir_allocation,
            "copy_file": fs.copy_allocation,
            "copy_dir": fs.copy_dir_allocation,
            "make_dir": fs.make_dir_allocation,
        }
        estimate = estimates.get(attr)
        if estimate is None:
            raise SericiteError(
                f"no allocation contract for VFS method '{attr}'", kind="internal_error"
            )
        if attr == "write_file":
            path = args[0] if args else kwargs.get("path")
            text = args[1] if len(args) > 1 else kwargs.get("text")
            amount = estimate(path, text)
        elif attr in ("rename_file", "rename_dir"):
            old_path = args[0] if args else kwargs.get("old_path")
            new_path = args[1] if len(args) > 1 else kwargs.get("new_path")
            amount = estimate(old_path, new_path)
        elif attr in ("copy_file", "copy_dir"):
            source_path = args[0] if args else kwargs.get("source_path")
            destination_path = (
                args[1] if len(args) > 1 else kwargs.get("destination_path")
            )
            amount = estimate(source_path, destination_path)
        else:
            path = args[0] if args else kwargs.get("path")
            amount = estimate(path)
        permit = self._meter(context).reserve(fs, "write", amount)
        self._meter(context).allocate(8)
        return permit

    def _charged_vfs_method(
        self,
        handle: VFSHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        context = kwargs.pop("_caller_context")
        result_meter = kwargs.pop("_caller_meter")
        permit = kwargs.pop("_allocation_permit", None)
        write_signature = (
            len(args) + len(kwargs) == 2
            and len(args) <= 2
            and set(kwargs) <= {"path", "text"}
            and (bool(args) or "path" in kwargs)
            and (len(args) > 1 or "text" in kwargs)
        )
        rename_signature = (
            len(args) + len(kwargs) == 2
            and len(args) <= 2
            and set(kwargs) <= {"old_path", "new_path"}
            and (bool(args) or "old_path" in kwargs)
            and (len(args) > 1 or "new_path" in kwargs)
        )
        copy_signature = (
            len(args) + len(kwargs) == 2
            and len(args) <= 2
            and set(kwargs) <= {"source_path", "destination_path"}
            and (bool(args) or "source_path" in kwargs)
            and (len(args) > 1 or "destination_path" in kwargs)
        )
        path_signature = (
            len(args) + len(kwargs) == 1 and len(args) <= 1 and set(kwargs) <= {"path"}
        )
        limits = self._file_operation_limits(context)
        if attr == "make_dir" and path_signature:
            path = args[0] if args else kwargs["path"]
            self._detached_vfs(handle).make_dir(path, permit=permit, limits=limits)
            result = None
        elif attr == "write_file" and write_signature:
            path = args[0] if args else kwargs["path"]
            text = args[1] if len(args) > 1 else kwargs["text"]
            self._detached_vfs(handle).write_file(
                path, text, permit=permit, limits=limits
            )
            result = None
        elif attr in ("rename_file", "rename_dir") and rename_signature:
            old_path = args[0] if args else kwargs["old_path"]
            new_path = args[1] if len(args) > 1 else kwargs["new_path"]
            getattr(self._detached_vfs(handle), attr)(
                old_path, new_path, permit=permit, limits=limits
            )
            result = None
        elif attr in ("copy_file", "copy_dir") and copy_signature:
            source_path = args[0] if args else kwargs["source_path"]
            destination_path = args[1] if len(args) > 1 else kwargs["destination_path"]
            getattr(self._detached_vfs(handle), attr)(
                source_path, destination_path, permit=permit, limits=limits
            )
            result = None
        elif attr == "list_dir" and path_signature:
            path = args[0] if args else kwargs.get("path")
            fs = self._detached_vfs(handle)
            if fs.list_dir_count(path) > limits.max_list_size:
                raise SericiteError(
                    "list size limit exceeded", kind="resource_exhausted"
                )
            result = fs.list_dir(path)
        elif (
            attr in {"read_file", "delete_file", "delete_dir", "path_exists"}
            and path_signature
        ):
            path = args[0] if args else kwargs["path"]
            result = getattr(self._detached_vfs(handle), attr)(path)
        else:
            raise SericiteError(f"invalid arguments for VFS.{attr}", kind="type_error")
        if result is not None:
            _estimate_size(result, meter=result_meter)
        return result
