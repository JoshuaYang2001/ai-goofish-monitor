"""Store-level monitoring notification models."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class StoreItemChange:
    """A single product change included in a store monitoring digest."""

    item_id: str
    title: str
    previous_want_count: int | None
    current_want_count: int | None
    want_count_delta: int | None
    previous_price: float | str | None = None
    current_price: float | str | None = None
    link: str | None = None


@dataclass(frozen=True, slots=True)
class StoreItemLifecycle:
    """A product entering or leaving the active store inventory."""

    item_id: str
    title: str
    link: str | None = None


@dataclass(frozen=True, slots=True)
class StoreMonitoringDigest:
    """Summary of one complete store monitoring run."""

    store_id: str
    task_name: str
    discovered_count: int
    succeeded_count: int
    failed_count: int
    changes: tuple[StoreItemChange, ...] = field(default_factory=tuple)
    added_items: tuple[StoreItemLifecycle, ...] = field(default_factory=tuple)
    removed_items: tuple[StoreItemLifecycle, ...] = field(default_factory=tuple)
    store_name: str | None = None
    is_initial_snapshot: bool = False
    monitored_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        # Accept lists at integration boundaries while keeping the immutable domain value.
        object.__setattr__(self, "changes", tuple(self.changes))
        object.__setattr__(self, "added_items", tuple(self.added_items))
        object.__setattr__(self, "removed_items", tuple(self.removed_items))

    @property
    def display_name(self) -> str:
        return self.store_name or self.store_id

    @property
    def change_count(self) -> int:
        return len(self.changes)

    @property
    def update_count(self) -> int:
        return self.change_count + len(self.added_items) + len(self.removed_items)
