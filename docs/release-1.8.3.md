# 1.8.3 release readiness

The `1.8.3-rc20` branch is the stabilization candidate for `1.8.3`. It combines the Frigate Light profile, bounded monitoring, restored PTT, transactional configuration updates, the flat low-cost UI, and the final operator workflow.

## Required checks before tagging 1.8.3

- Run `python3 -m unittest tests/test_regressions.py`.
- Run `node tests/frontend.test.js` and `node tests/settings-save.test.js`.
- Run the Chrome checks described in `docs/ui-tests.md` at 1280 px and 390 px.
- Deploy the candidate to both AK3918 cameras and confirm the reported version.
- Confirm HTTPS and both RTSP streams after deployment and after one reboot.
- Keep FTP and Telnet closed after deployment.
- Sample status, available memory, RTSP and storage repeatedly for at least two minutes. There must be no service loss, monotonic memory collapse, or malformed status response.
- Exercise configuration readback, Services filtering, Operator mode, Records filtering and PTT on the primary test camera.
- Do not run PTT on the secondary camera unless that restriction is explicitly lifted.
- Repeat the long-duration RTSP and storage-full tests before creating the final tag.

## Release procedure

1. Merge the accepted candidate into the release branch.
2. Set `VERSION` and cache stamps to `1.8.3`.
3. Re-run every required check above.
4. Tag the tested commit as `v1.8.3`.
5. Deploy the exact tagged files; do not rebuild between tagging and deployment.

The remaining long-duration RTSP and storage-full tests are release gates because they cannot be established by the host test suite alone.
