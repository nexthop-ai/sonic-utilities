from .base import ImageVersion, VersionComparer
from ..common import IMAGE_PREFIX
import re
from ..exception import SonicRuntimeException


class NexthopImageVersion(ImageVersion):
    """
    Concrete product for Nexthop's release naming convention (v2):

    <Rel>.<Maj>[-EFTX][.<Min>][M].Nexthop

    See "IND20" for more details.
    """
    def __init__(self, version_str):
        # can't impose ordering on non-release images (ie. main, custom branches)
        if not NexthopImageVersion.is_valid_version(version_str):
            raise SonicRuntimeException("Invalid version string format")
        self.year, self.month = self._parse_release_train(version_str)
        self.major, self.eft, self.minor = self._parse_sub_version(version_str)

    def _parse_release_train(self, version):
        tokens = version.split(".")
        token = re.sub(IMAGE_PREFIX, '', tokens[0], 1)
        year, month = token[:4], token[4:]
        return int(year), int(month)

    def _parse_sub_version(self, version):
        tokens = version.split(".")

        major, eft, minor = -1, -1, -1
        if tokens[1].isdigit():
            major = int(tokens[1])
        elif "-EFT" in tokens[1]:
            items = tokens[1].split("-EFT")
            major = int(items[0])
            if items[1][-1] == "M":  # ex. 202505.3-EFT2M
                eft = int(items[1][:-1])
            else:
                eft = int(items[1])
        elif tokens[-1] == "M":
            major = int(tokens[1][:-1])
        else:
            return major, eft, minor

        if tokens[2].isdigit():
            minor = int(tokens[2])
        elif tokens[-1] == "M":  # ex. 202505.3.1M
            minor = int(tokens[2][:-1])
        return major, eft, minor

    def __eq__(self, other_version):
        is_same = self.year == other_version.year
        is_same &= self.month == other_version.month
        is_same &= self.major == other_version.major
        is_same &= self.eft == other_version.eft
        is_same &= self.minor == other_version.minor
        return is_same

    def is_newer_than(self, other):
        if self != other:
            if other.year != self.year:
                return other.year < self.year
            elif other.month != self.month:
                return other.month < self.month
            elif other.major != self.major:
                return other.major < self.major
            elif other.eft != self.eft:
                return other.eft < self.eft
            elif other.minor != self.minor:
                return other.minor < self.minor
        return False

    @staticmethod
    def is_valid_version(version_str):
        rel_train_prefix = rf"{IMAGE_PREFIX}[0-9]{{6}}"
        return re.match(rel_train_prefix, version_str) is not None


class NexthopVersionComparer(VersionComparer):
    def _create_image_version(self, version_str: str) -> ImageVersion:
        return NexthopImageVersion(version_str)

    def _is_valid_version(self, version_str):
        return NexthopImageVersion.is_valid_version(version_str)
