Public keys (*.pub) of the owner who signs the update packages (docs/linux-port/upgrade-3.2/sign.md).
One file per key: "<64 hex digits> comment". The repository holds public keys only, never a private key.
update66.sh also reads /mnt/config/update-keys/*.pub (keys added on the camera itself, kept across updates).
No key yet: updates are accepted unsigned (UPDATE_REQUIRE_SIG=0) and UPDATE_REQUIRE_SIG=1 behaves as 0 with a warning.
