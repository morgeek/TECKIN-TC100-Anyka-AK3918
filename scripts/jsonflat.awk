# jsonflat.awk — flatten a JSON document into one line per scalar:
#
#   <path> TAB <type> TAB <value>
#
#   path   jq-style: .a.b, .list[0].c ("." for a top-level scalar)
#   type   s string, n number, b boolean, z null
#   value  strings decoded (\uXXXX as UTF-8); backslash, tab and newline
#          written back as \\ \t \n so one scalar stays on one line
#
# Replaces jq on the camera (235 KB in the flash image). BusyBox awk.
#   awk -f jsonflat.awk [-v require=object|array] file.json
# Exit 2 (message on stderr, nothing trusted) on malformed input or when the
# top-level value is not of the required type.

function fail(msg) { printf "jsonflat: %s at offset %d\n", msg, pos > "/dev/stderr"; bad = 1; exit 2 }
function ws() { while (pos <= len && index(" \t\r\n", substr(s, pos, 1))) pos++ }
function hexval(h,   i, v, c) {
    v = 0
    for (i = 1; i <= 4; i++) {
        c = index("0123456789abcdef", tolower(substr(h, i, 1)))
        if (!c) fail("bad \\u escape")
        v = v * 16 + c - 1
    }
    return v
}
function utf8(cp) {
    if (cp < 128) return sprintf("%c", cp)
    if (cp < 2048) return sprintf("%c%c", 192 + int(cp / 64), 128 + cp % 64)
    if (cp < 65536) return sprintf("%c%c%c", 224 + int(cp / 4096), 128 + int(cp / 64) % 64, 128 + cp % 64)
    return sprintf("%c%c%c%c", 240 + int(cp / 262144), 128 + int(cp / 4096) % 64, 128 + int(cp / 64) % 64, 128 + cp % 64)
}
function str(   out, c, e, cp, lo) {
    # pos is on the opening quote
    pos++; out = ""
    while (1) {
        if (pos > len) fail("unterminated string")
        c = substr(s, pos, 1)
        if (c == "\"") { pos++; return out }
        if (c == "\\") {
            e = substr(s, pos + 1, 1)
            if (e == "u") {
                cp = hexval(substr(s, pos + 2, 4)); pos += 6
                if (cp >= 55296 && cp < 56320 && substr(s, pos, 2) == "\\u") {
                    lo = hexval(substr(s, pos + 2, 4))
                    if (lo >= 56320 && lo < 57344) { cp = 65536 + (cp - 55296) * 1024 + (lo - 56320); pos += 6 }
                }
                out = out utf8(cp); continue
            }
            if (e == "\"") out = out "\""
            else if (e == "\\") out = out "\\"
            else if (e == "/") out = out "/"
            else if (e == "b") out = out "\b"
            else if (e == "f") out = out "\f"
            else if (e == "n") out = out "\n"
            else if (e == "r") out = out "\r"
            else if (e == "t") out = out "\t"
            else fail("bad escape")
            pos += 2; continue
        }
        # Plain run up to the next quote or backslash, in bounded windows
        # (substr(s, pos) would copy the rest of the document every time).
        if (match(substr(s, pos, 256), /^[^"\\]+/)) { out = out substr(s, pos, RLENGTH); pos += RLENGTH; continue }
        out = out c; pos++
    }
}
function emit(path, type, v) {
    gsub(/\\/, "\\\\", v); gsub(/\t/, "\\t", v); gsub(/\n/, "\\n", v)
    printf "%s\t%s\t%s\n", (path == "" ? "." : path), type, v
}
function value(path,   c, k, i, num) {
    ws()
    if (pos > len) fail("unexpected end")
    c = substr(s, pos, 1)
    if (c == "{") {
        pos++; ws()
        if (substr(s, pos, 1) == "}") { pos++; return "object" }
        while (1) {
            ws(); if (substr(s, pos, 1) != "\"") fail("expected a key")
            k = str(); ws()
            if (substr(s, pos, 1) != ":") fail("expected :")
            pos++
            value(path "." k)
            ws(); c = substr(s, pos, 1); pos++
            if (c == "}") return "object"
            if (c != ",") fail("expected , or }")
        }
    }
    if (c == "[") {
        pos++; ws(); i = 0
        if (substr(s, pos, 1) == "]") { pos++; return "array" }
        while (1) {
            value(path "[" i "]"); i++
            ws(); c = substr(s, pos, 1); pos++
            if (c == "]") return "array"
            if (c != ",") fail("expected , or ]")
        }
    }
    if (c == "\"") { emit(path, "s", str()); return "string" }
    if (substr(s, pos, 4) == "true") { pos += 4; emit(path, "b", "true"); return "boolean" }
    if (substr(s, pos, 5) == "false") { pos += 5; emit(path, "b", "false"); return "boolean" }
    if (substr(s, pos, 4) == "null") { pos += 4; emit(path, "z", ""); return "null" }
    num = substr(s, pos, 64)
    if (match(num, /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?/)) {
        pos += RLENGTH; emit(path, "n", substr(num, 1, RLENGTH)); return "number"
    }
    fail("unexpected character")
}
{ s = s $0 "\n" }
END {
    if (bad) exit 2
    len = length(s); pos = 1
    top = value("")
    ws()
    if (pos <= len) fail("trailing data")
    if (require != "" && top != require) { pos = 1; fail("top-level value is not an " require) }
}
