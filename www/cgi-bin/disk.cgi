#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
source ./func.cgi
PATH="/bin:/sbin:/usr/bin:/usr/sbin"

df_text="$(df -h 2>/dev/null)"
iostat_text="$(iostat -d -k 2>/dev/null)"
mount_text="$(mount 2>/dev/null)"

root_usage="$(printf '%s\n' "$df_text" | awk '$NF=="/"{print $5; exit}')"
[ -n "$root_usage" ] || root_usage="n/a"
filesystem_count="$(printf '%s\n' "$df_text" | awk 'NR>1{count++} END{print count+0}')"
mount_count="$(printf '%s\n' "$mount_text" | awk 'NF{count++} END{print count+0}')"
mmc_mount="$(printf '%s\n' "$mount_text" | awk '/mmcblk/{print $3 " (" $1 ")"; exit}')"
[ -n "$mmc_mount" ] || mmc_mount="n/a"

cat << EOF
<div class='info-grid'>
    <div class='info-side'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3s-3.6 3-8 3s-8-1.3-8-3zM4 12c0 1.7 3.6 3 8 3s8-1.3 8-3M4 17c0 1.7 3.6 3 8 3s8-1.3 8-3'/></svg><span>Disk Summary</span></span></p></header>
            <div class='card-content'>
                Root usage:
                <pre class='info-pre'>$root_usage</pre>
                Filesystems:
                <pre class='info-pre'>$filesystem_count</pre>
                Mount points:
                <pre class='info-pre'>$mount_count</pre>
                SD mount:
                <pre class='info-pre'>$mmc_mount</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M5 19h14M7 15l3-3l3 2l4-5'/></svg><span>Disk IO Snapshot (kB)</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre'>$iostat_text</pre>
            </div>
        </div>
    </div>

    <div class='info-main'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3s-3.6 3-8 3s-8-1.3-8-3zM4 12c0 1.7 3.6 3 8 3s8-1.3 8-3M4 17c0 1.7 3.6 3 8 3s8-1.3 8-3'/></svg><span>Disk Space Information</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$df_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M3 7h7l2 2h9v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/></svg><span>Mounts</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$mount_text</pre>
            </div>
        </div>
    </div>
</div>

</body>
</html>
EOF
