# Nginx Outage Postmortem — 2026-04-14

## Timeline

**Outage start**: 2026-04-14 04:10:56 UTC  
**Outage duration**: ~3 days  
**Recovery**: 2026-04-17 (manual restart)  
**Impact**: bet-agent.ru website down

---

## Root Cause

**nginx was killed by an external process, NOT by the OOM killer.**

### Evidence

1. **journalctl nginx logs** (2026-04-14 04:10:56):
   ```
   nginx.service: Main process exited, code=killed, status=9/KILL
   nginx.service: Killing process 3391184 (nginx) with signal SIGKILL
   nginx.service: Failed with result 'signal'
   ```

2. **No OOM killer activity**:
   - No "Out of memory" or "oom_kill" entries in kernel logs
   - No "killed process" entries in dmesg or journalctl -k
   - Memory usage at time of incident: 6.2M peak (extremely low)

3. **Concurrent kills**:
   - betagent-bot.service also killed at 04:07:38, 04:10:56, 04:11:37, 04:12:31, 04:14:12
   - Multiple services received SIGKILL (status=9) within 7-minute window

4. **System logs**:
   - Only unrelated SSH errors around the same time
   - No system-level memory pressure or panic events

### Conclusion

Most likely causes (in order of probability):
1. **Manual kill** — administrator or script sent `kill -9` to nginx/betagent processes
2. **Resource manager** — hosting provider's resource enforcement (CPU/memory quota exceeded)
3. **Security tool** — some monitoring/security process killed services

**NOT an OOM event** — memory usage was minimal (6.2M peak), and OOM killer leaves explicit kernel log entries which are absent.

---

## Why Nginx Stayed Down for 3 Days

nginx was configured with `Restart=no` or had no automatic restart policy, so:
- systemd did NOT auto-restart after SIGKILL
- Service remained in "failed" state until manual intervention

---

## Remediation

### 1. Monitoring Added ✅

Created `/root/betagent/monitor_nginx.sh`:
- **Check 1**: Service status (`systemctl is-active nginx`)
- **Check 2**: HTTP availability (`curl localhost:80`)
- **Alert mechanism**: Telegram message on failure
- **Deduplication**: One alert per failure (no spam)

Scheduled via cron:
```
*/10 * * * * /root/betagent/monitor_nginx.sh >> /root/betagent/logs/nginx_monitor.log 2>&1
```

**Alert triggered when**:
- nginx service is not active → "nginx service is NOT active"
- localhost:80 HTTP check fails → "nginx HTTP check FAILED"

### 2. Next Steps (Recommended)

1. **Enable auto-restart** for nginx:
   ```
   systemctl edit nginx
   # Add:
   [Service]
   Restart=always
   RestartSec=5s
   ```

2. **Investigate hosting provider logs** — check for resource quota violations or automated kills

3. **Review betagent-bot restart policy** — it was also killed and restarted 5 times in 7 minutes

4. **Enable systemd rate limiting** — prevent rapid restart loops if issue recurs

---

## Summary

| Question | Answer |
|----------|--------|
| **Root cause** | External SIGKILL (not OOM). Most likely manual kill or hosting provider resource enforcement. |
| **Why 3 days down** | No auto-restart policy. Service stayed in failed state until manual restart. |
| **Monitoring added** | ✅ Yes — cron job every 10 min checking service + HTTP, Telegram alerts on failure |
| **Alert trigger** | Service down OR localhost:80 not responding |

---

**Generated**: 2026-04-18  
**Investigator**: Claude Code (automated analysis)
