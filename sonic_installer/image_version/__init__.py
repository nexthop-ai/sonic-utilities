from .nexthop import NexthopVersionComparer


def is_downgrade(curr_version, new_version):
    comparer = NexthopVersionComparer()
    return comparer.is_downgrade(curr_version, new_version)


__all__ = ["is_downgrade"]
