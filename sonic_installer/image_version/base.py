from abc import ABC, abstractmethod


class ImageVersion(ABC):
    """Abstraction of a generic image version string."""

    @abstractmethod
    def is_newer_than(self, other) -> bool:
        """Return True if moving from ``self`` -> ``other`` is a downgrade"""
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def is_valid_version(version_str) -> bool:
        raise NotImplementedError


class VersionComparer(ABC):
    """
    Abstraction of a class that compares two version strings.

    External modules should use is_downgrade() to faciliate version string comparisons;
    the other methods are intended to be private to this class.
    """

    @abstractmethod
    def _create_image_version(self, version_str: str) -> ImageVersion:
        """Factory method: construct the concrete ``ImageVersion`` for
        ``version_str``. Overridden by each concrete comparer."""
        raise NotImplementedError

    @abstractmethod
    def _is_valid_version(self, version_str):
        raise NotImplementedError

    def is_downgrade(self, curr_version_str: str, target_version_str: str) -> bool:
        """Return True if installing ``target_version_str`` over the currently
        running ``curr_version_str`` would be a downgrade."""
        if not self.valid_versions(curr_version_str, target_version_str):
            return False

        curr = self._create_image_version(curr_version_str)
        target = self._create_image_version(target_version_str)
        return curr.is_newer_than(target)

    def valid_versions(self, *versions) -> bool:
        return all(self._is_valid_version(v) for v in versions)
