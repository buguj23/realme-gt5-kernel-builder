# Realme GT5 ossi ROM overlay

`scripts/rom-build-local.sh` stages this overlay into the matching Infinity-X or LineageOS checkout. The branch table and input requirements are in [ROM_BUILD.md](../docs/ROM_BUILD.md).

The builder uses the verified stock LP layout, stages the matching DTB and DTBO, and preserves distinct normal and Recovery module orders. It generates the vendor tree from the verified stock dump with extract-utils. It verifies the resulting target-files and OTA before collecting artifacts.
