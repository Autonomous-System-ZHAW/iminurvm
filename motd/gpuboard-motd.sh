# /etc/profile.d/gpuboard-motd.sh
# Show the claim banner in interactive shells, incl. VS Code Remote terminals
# (those do not trigger /etc/update-motd.d). Once per shell tree.
case $- in
  *i*)
    if [ -z "${GPUBOARD_MOTD_SHOWN:-}" ] && command -v vm-motd >/dev/null 2>&1; then
      export GPUBOARD_MOTD_SHOWN=1
      vm-motd || true
    fi
    ;;
esac
