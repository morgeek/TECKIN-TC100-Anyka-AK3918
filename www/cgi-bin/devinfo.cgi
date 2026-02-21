#!/bin/sh


source ./func.cgi
source /mnt/scripts/common_functions.sh


echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

cat << EOF

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M8 4h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM10 17h4'/></svg><span>Device version</span></span></p></header>
    <div class='card-content'>
        Release:
        <pre>$(cat /usr/local/factory_fw_version)</pre>
        System:
        <pre>$(uname -a)</pre>
        CPU:
        <pre>$(cat /proc/cpuinfo)</pre>
        <pre>$(/mnt/bin/busybox strings /tmp/start_message  | grep -m1 "clocks:")</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7h16v10H4zM8 11h8M8 14h5M7 7V5M17 7V5'/></svg><span>Bootloader Information</span></span></p></header>
    <div class='card-content'>
        Your Bootloader Version is:
        <pre>$(/mnt/bin/busybox strings /dev/mtd0 | grep -m1 "U-Boot 2")</pre>
        Your CMDline is:
        <pre>$(cat /proc/cmdline)</pre>
        <a target="_blank" href="cgi-bin/dumpbootloader.cgi">Download Bootloader</a>
    </div>
</div>


</body>
</html>
EOF
