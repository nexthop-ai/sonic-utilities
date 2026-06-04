from .base import ImageVersion, VersionComparer
from ..common import IMAGE_PREFIX
import re


class SonicImageVersion(ImageVersion):
    def __init__(self, version_str):
        self.year, self.month = self._parse_release_train(version_str)
        self.patch_num = self._parse_patch_number(version_str)

    def _parse_patch_number(self, version):
        token = version.split(".")[1]
        return int(token) if token.isdigit() else -1

    def _parse_release_train(self, version):
        tokens = version.split(".")
        token = re.sub(IMAGE_PREFIX, '', tokens[0], 1)
        year, month = token[:4], token[4:]
        return int(year), int(month)

    def __eq__(self, other):
        is_equal = self.year == other.year
        is_equal &= self.month == other.month
        is_equal &= self.patch_num == other.patch_num
        return is_equal

    def is_newer_than(self, other):
        if self != other:
            if self.year != other.year:
                return other.year < self.year
            if self.month != other.month:
                return other.month < self.month
            if self.patch_num != other.patch_num:
                return other.patch_num < self.patch_num
        return False

    @staticmethod
    def is_valid_version(version_str):
        rel_train_prefix = rf"{IMAGE_PREFIX}[0-9]{{6}}"
        return re.match(rel_train_prefix, version_str) is not None


class SonicVersionComparer(VersionComparer):
    def _create_image_version(self, version_str: str) -> ImageVersion:
        return SonicImageVersion(version_str)

    def _is_valid_version(self, version_str):
        return SonicImageVersion.is_valid_version(version_str)
