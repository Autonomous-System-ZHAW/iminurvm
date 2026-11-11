# /etc/profile.d/gpuboard-motd.sh
# Source from /etc/profile.d and the system interactive bash configuration.
case $- in
  *i*)
    if [ -z "${GPUBOARD_MOTD_SHOWN:-}" ]; then
      unset GPUBOARD_MOTD_SHOWN
      GPUBOARD_MOTD_SHOWN=1
      if [ ! -x /opt/gpuboard/venv/bin/vm-motd ]; then
        printf '%s\n' 'gpu-board: status unavailable: vm-motd is not installed' >&2
      elif ! command -v timeout >/dev/null 2>&1; then
        printf '%s\n' 'gpu-board: status unavailable: timeout command is missing' >&2
      else
        if timeout --kill-after=1s 3s /opt/gpuboard/venv/bin/vm-motd; then
          :
        else
          gpuboard_motd_exit=$?
          if [ "$gpuboard_motd_exit" -eq 124 ] || [ "$gpuboard_motd_exit" -eq 137 ]; then
            printf '%s\n' 'gpu-board: status unavailable: request timed out' >&2
          fi
          unset gpuboard_motd_exit
        fi
      fi
    fi
    ;;
esac
