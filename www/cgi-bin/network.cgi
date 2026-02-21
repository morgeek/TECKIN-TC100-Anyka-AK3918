#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
source ./func.cgi
PATH="/bin:/sbin:/usr/bin:/usr/sbin"

cat << EOF

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 12h6M14 12h6M10 8l4 4l-4 4'/></svg><span>Interfaces</span></span></p></header>
    <div class='card-content'>
        <pre>$(ifconfig; iwconfig)</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7h9M13 7l3-3M13 7l3 3M20 17H11M11 17l-3-3M11 17l-3 3'/></svg><span>Routes</span></span></p></header>
    <div class='card-content'>
        <pre>$(route)</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.3 2.5 13.7 0 18M12 3c-2.5 2.3-2.5 13.7 0 18'/></svg><span>DNS</span></span></p></header>
    <div class='card-content'>
        <pre>$(cat /etc/resolv.conf)</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M7 4h10v6H7zM12 10v10M9 16h6'/></svg><span>Opened ports</span></span></p></header>
    <div class='card-content'>
        <pre>$(netstat -l)</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 12a3 3 0 0 1 3-3h3M15 12a3 3 0 0 1-3 3H9M7 9l-2 2l2 2M17 9l2 2l-2 2'/></svg><span>Connections</span></span></p></header>
    <div class='card-content'>
        <pre>$(netstat)</pre>
    </div>
</div>

</body>
</html>
EOF

