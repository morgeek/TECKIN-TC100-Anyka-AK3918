import time

in_path = "~/Downloads/tc100-fix/uart-in.txt"

commands = [
    "setenv sdload 'fatload mmc 0 0x82000000 tc100test/oipc.img; fatload mmc 0 0x80900000 tc100test/oipcrd.gz'",
    "setenv sdboot 'setenv bootargs console=ttySAK0,115200n8 mem=64M root=/dev/ram0 rdinit=/init initrd=0x80900000,6921241 mtdparts=spi0.0:8192k(all)ro initcall_blacklist=gpio_keys_init panic=10 loglevel=7; bootm 0x82000000'",
    "setenv bootcmd 'run sdload sdboot; run boot_normal'",
    "printenv sdload sdboot bootcmd",
    "mw.b 0x83000000 0 0x1000",
    "mw.l 0x83000000 ffffffff 1",
    "env export -b -s 0xff8 0x83000008",
    "crc32 0x83000008 0xff8 0x83000004",
    "sf probe 0:0 20000000 0",
    "sf erase 0x23a000 0x1000",
    "sf write 0x83000000 0x23a000 0x1000",
    "sf read 0x83100000 0x23a000 0x1000",
    "cmp.b 0x83000000 0x83100000 0x1000"
]

for cmd in commands:
    with open(in_path, "a") as f:
        f.write(cmd + "\r")
    time.sleep(0.3)

