#!/bin/bash
# ══ CagentOS 数据备份脚本 ══
#
# 备份内容:
#   1. SQLite 数据库 (在线备份, WAL 模式安全)
#   2. knowledge/ 目录 (29 篇归档, 不在 git 里, 删了就没了)
#   3. .env (生产密钥, 权限 600)
#
# 保留策略: 30 天
# 定时任务: crontab -e → 0 3 * * * /opt/cagent-os/scripts/backup.sh
#
# ⚠️  备份文件和数据库在同一台机器上, 机器挂了两个一起没
#     必须同步到服务器之外 (见脚本末尾提示)

set -euo pipefail

APP_DIR="/opt/cagent-os"
BACKUP_DIR="${APP_DIR}/data-backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_SUBDIR="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "${BACKUP_SUBDIR}"

# ── 1. SQLite 在线备份 ──
# sqlite3 .backup 命令在 WAL 模式下安全, 不需要停服务
echo "[$(date)] Backing up SQLite databases..."
for db_path in "${APP_DIR}"/data/*.db; do
    [ -f "$db_path" ] || continue
    db_name=$(basename "$db_path")
    sqlite3 "$db_path" ".backup '${BACKUP_SUBDIR}/${db_name}'"
    echo "  ✓ ${db_name}"
done

# ── 2. knowledge/ 目录 (内容资产, 不在 git 里) ──
if [ -d "${APP_DIR}/knowledge" ]; then
    echo "[$(date)] Backing up knowledge/..."
    cp -r "${APP_DIR}/knowledge" "${BACKUP_SUBDIR}/knowledge"
    file_count=$(find "${BACKUP_SUBDIR}/knowledge" -type f | wc -l)
    echo "  ✓ knowledge/ (${file_count} files)"
else
    echo "[$(date)] WARNING: knowledge/ directory not found, skipping"
fi

# ── 3. .env (生产密钥) ──
if [ -f "${APP_DIR}/.env" ]; then
    echo "[$(date)] Backing up .env..."
    cp "${APP_DIR}/.env" "${BACKUP_SUBDIR}/.env"
    chmod 600 "${BACKUP_SUBDIR}/.env"
    echo "  ✓ .env (chmod 600)"
fi

# ── 4. 清理 30 天以上的旧备份 ──
echo "[$(date)] Cleaning old backups (>30 days)..."
find "${BACKUP_DIR}" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \; 2>/dev/null || true

# ── 汇总 ──
SIZE=$(du -sh "${BACKUP_SUBDIR}" | cut -f1)
echo ""
echo "══════════════════════════════════════════════════"
echo "  Backup completed: ${TIMESTAMP}"
echo "  Location: ${BACKUP_SUBDIR}"
echo "  Size: ${SIZE}"
echo "══════════════════════════════════════════════════"
echo ""
echo "⚠️  请将备份同步到服务器之外:"
echo "   rsync:  rsync -avz ${BACKUP_SUBDIR} user@backup-host:/backups/cagentos/"
echo "   rclone: rclone copy ${BACKUP_SUBDIR} remote:cagentos-backups/"
echo "   scp:    scp -r ${BACKUP_SUBDIR} user@backup-host:/backups/cagentos/"
echo ""
