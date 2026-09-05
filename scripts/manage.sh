#!/usr/bin/env bash
# NeoCortex unified service & snapshot manager.
#
# Single entry point for service lifecycle (start/stop) and data persistence
# (snapshot save/list/load/delete).
#
# Usage:
#   ./scripts/manage.sh start [--fresh]    # Start services (persist data by default)
#   ./scripts/manage.sh stop [--all]       # Stop services
#   ./scripts/manage.sh status             # Show running services
#   ./scripts/manage.sh snapshot <cmd>     # Manage snapshots
#   ./scripts/manage.sh help               # Full help
#
# Environment overrides:
#   MCP_PORT=8000   INGESTION_PORT=8001   MAX_WAIT=60

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MCP_PORT="${MCP_PORT:-8000}"
INGESTION_PORT="${INGESTION_PORT:-8001}"
MAX_WAIT="${MAX_WAIT:-60}"
PIDFILE_MCP="$PROJECT_DIR/.mcp.pid"
PIDFILE_INGESTION="$PROJECT_DIR/.ingestion.pid"
LOGDIR="$PROJECT_DIR/log"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
BACKUPDIR="$PROJECT_DIR/backups"
MEDIA_STORE="$PROJECT_DIR/media_store"

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

log()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

pids_on_port() {
    # Try lsof first (macOS + some Linux), fall back to ss+awk (Linux)
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti ":$1" 2>/dev/null || true
    else
        ss -tlnp "sport = :$1" 2>/dev/null \
            | awk 'NR>1 { match($0, /pid=([0-9]+)/, m); if (m[1]) print m[1] }' || true
    fi
}

kill_port() {
    local port="$1"
    local pids
    pids=$(pids_on_port "$port")
    if [[ -n "$pids" ]]; then
        log "Killing existing process(es) on port $port (PIDs: $pids)..."
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        # Force-kill stragglers
        pids=$(pids_on_port "$port")
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill -9 2>/dev/null || true
            sleep 1
        fi
    fi
}

kill_pidfile() {
    local pidfile="$1"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(<"$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -f "$pidfile"
    fi
}

wait_for_healthy() {
    local url="$1" max="$2" elapsed=0
    log "Waiting for $url (up to ${max}s)..."
    while (( elapsed < max )); do
        if curl -sf "$url" >/dev/null 2>&1; then
            ok "Healthy: $url (${elapsed}s)"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    fail "Service at $url not healthy after ${max}s"
}

wait_for_postgres() {
    log "Waiting for PostgreSQL..."
    local elapsed=0
    while (( elapsed < MAX_WAIT )); do
        if docker compose -f "$COMPOSE_FILE" exec -T postgres \
            pg_isready -U neocortex -d neocortex >/dev/null 2>&1; then
            ok "PostgreSQL ready (${elapsed}s)"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    fail "PostgreSQL not ready after ${MAX_WAIT}s"
}

apply_migrations() {
    log "Applying migrations..."
    uv run python -m neocortex.migrations
    ok "Migrations applied"
}

require_pg_running() {
    if ! docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U neocortex -d neocortex >/dev/null 2>&1; then
        fail "PostgreSQL is not running. Run '$0 start' first."
    fi
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

do_start() {
    local fresh=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --fresh) fresh=true; shift ;;
            *) fail "Unknown option for start: $1" ;;
        esac
    done

    cd "$PROJECT_DIR"
    mkdir -p "$LOGDIR"

    # --- Clean up old instances ---
    log "Clearing old instances..."
    kill_pidfile "$PIDFILE_MCP"
    kill_pidfile "$PIDFILE_INGESTION"
    kill_port "$MCP_PORT"
    kill_port "$INGESTION_PORT"

    # --- PostgreSQL ---
    if $fresh; then
        log "Starting with fresh volume..."
        docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
    else
        log "Starting with existing data..."
    fi

    docker compose -f "$COMPOSE_FILE" up -d postgres 2>&1 || {
        log "Container conflict — removing stale container and retrying..."
        docker rm -f neocortex-postgres 2>/dev/null || true
        docker compose -f "$COMPOSE_FILE" up -d postgres 2>&1
    }
    wait_for_postgres
    apply_migrations

    # --- Source .env (without overwriting caller-exported vars) ---
    # Using read-based parsing instead of `set -a; source .env` so that
    # env vars already set by the caller (e.g. run_e2e.sh) are preserved.
    if [[ -f "$PROJECT_DIR/.env" ]]; then
        while IFS='=' read -r key value; do
            # Skip comments and blank lines
            [[ "$key" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$key" ]] && continue
            # Strip leading/trailing whitespace and optional 'export' prefix from key
            key="${key#"${key%%[![:space:]]*}"}"
            key="${key%"${key##*[![:space:]]}"}"
            key="${key#export }"
            # Strip surrounding quotes from value
            value="${value#\"}" ; value="${value%\"}"
            value="${value#\'}" ; value="${value%\'}"
            # Only export if the variable is not already set by the caller
            if [[ -z "${!key+x}" ]]; then
                export "$key=$value"
            fi
        done < "$PROJECT_DIR/.env"
    fi

    # --- MCP server ---
    local tokens_file="${NEOCORTEX_DEV_TOKENS_FILE:-dev_tokens.json}"
    log "Starting MCP server (port $MCP_PORT, tokens: $tokens_file)..."
    NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE="$tokens_file" \
    NEOCORTEX_MOCK_DB=false \
    uv run python -m neocortex \
        >"$LOGDIR/mcp_stdout.log" 2>&1 &
    echo $! > "$PIDFILE_MCP"
    log "  PID $(cat "$PIDFILE_MCP") → log: $LOGDIR/mcp_stdout.log"

    # Wait for MCP to be healthy before starting ingestion server —
    # both run create_services() which provisions shared schemas, and
    # concurrent schema creation causes "tuple concurrently updated" errors.
    wait_for_healthy "http://127.0.0.1:${MCP_PORT}/health" "$MAX_WAIT"

    # --- Ingestion server ---
    log "Starting ingestion server (port $INGESTION_PORT)..."
    NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE="$tokens_file" \
    NEOCORTEX_MOCK_DB=false \
    uv run python -m neocortex.ingestion \
        >"$LOGDIR/ingestion_stdout.log" 2>&1 &
    echo $! > "$PIDFILE_INGESTION"
    log "  PID $(cat "$PIDFILE_INGESTION") → log: $LOGDIR/ingestion_stdout.log"

    # --- Health check for ingestion ---
    wait_for_healthy "http://127.0.0.1:${INGESTION_PORT}/health" "$MAX_WAIT"

    ok "All services running. Ready for testing."
    echo ""
    echo "  MCP server:       http://127.0.0.1:${MCP_PORT}"
    echo "  Ingestion API:    http://127.0.0.1:${INGESTION_PORT}"
    echo "  Admin token:      admin-token"
    echo "  Dev token:        claude-code-work"
    echo ""
    echo "  Stop with:        ./scripts/manage.sh stop"
    echo "  Logs:             tail -f $LOGDIR/mcp_stdout.log $LOGDIR/ingestion_stdout.log"
}

do_stop() {
    local stop_all=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --all) stop_all=true; shift ;;
            *) fail "Unknown option for stop: $1" ;;
        esac
    done

    log "Stopping NeoCortex services..."
    kill_pidfile "$PIDFILE_MCP"
    kill_pidfile "$PIDFILE_INGESTION"
    kill_port "$MCP_PORT"
    kill_port "$INGESTION_PORT"

    if $stop_all; then
        docker compose -f "$COMPOSE_FILE" down 2>/dev/null || true
        ok "All services stopped (data preserved)."
    else
        ok "App services stopped. PostgreSQL still running."
    fi
}

do_snapshot() {
    local subcmd="${1:-help}"
    shift || true
    case "$subcmd" in
        save)   snapshot_save "$@" ;;
        list)   snapshot_list "$@" ;;
        load)   snapshot_load "$@" ;;
        delete) snapshot_delete "$@" ;;
        *)      fail "Unknown snapshot command: $subcmd" ;;
    esac
}

snapshot_save() {
    # Validate: exactly one arg matching [a-zA-Z0-9_-]+
    if [[ $# -ne 1 ]]; then
        fail "Usage: $0 snapshot save <name>"
    fi
    local name="$1"
    if [[ ! "$name" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        fail "Snapshot name must match [a-zA-Z0-9_-]+ (got: $name)"
    fi

    require_pg_running

    local filename="${name}-$(date +%Y%m%d-%H%M%S)"
    local tmpdir
    tmpdir=$(mktemp -d)

    # pg_dump
    log "Dumping database..."
    docker compose -f "$COMPOSE_FILE" exec -T \
        -e PGPASSWORD=neocortex postgres \
        pg_dump -U neocortex -d neocortex --clean --if-exists \
        | gzip > "$tmpdir/db.sql.gz"

    # Copy media_store if non-empty
    local has_media=false
    if [[ -d "$MEDIA_STORE" ]] && [[ -n "$(ls -A "$MEDIA_STORE" 2>/dev/null)" ]]; then
        log "Bundling media_store..."
        cp -r "$MEDIA_STORE" "$tmpdir/media_store"
        has_media=true
    fi

    # Capture PG version
    local pg_ver
    pg_ver=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_dump --version | head -1 | tr -d '\r')

    # Write metadata
    local created_at
    created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "$tmpdir/snapshot.json" <<METAEOF
{
  "name": "$name",
  "created_at": "$created_at",
  "pg_version": "$pg_ver",
  "has_media": $has_media,
  "original_host": "$(hostname)"
}
METAEOF

    # Create archive
    mkdir -p "$BACKUPDIR"
    local archive_path="$BACKUPDIR/${filename}.tar.gz"
    tar -czf "$archive_path" -C "$tmpdir" .

    if [[ -n "${NEOCORTEX_SNAPSHOT_PATH_FILE:-}" ]]; then
        local receipt_tmp="${NEOCORTEX_SNAPSHOT_PATH_FILE}.tmp"
        printf '%s\n' "$archive_path" >"$receipt_tmp"
        mv "$receipt_tmp" "$NEOCORTEX_SNAPSHOT_PATH_FILE"
    fi

    # Cleanup temp dir
    rm -rf "$tmpdir"

    local size
    size=$(ls -lh "$archive_path" | awk '{print $5}')
    ok "Snapshot saved: $BACKUPDIR/${filename}.tar.gz ($size)"
}

snapshot_list() {
    if [[ ! -d "$BACKUPDIR" ]] || [[ -z "$(ls -A "$BACKUPDIR"/*.tar.gz 2>/dev/null)" ]]; then
        log "No snapshots found. Create one with: $0 snapshot save <name>"
        return 0
    fi

    printf '%-30s %-22s %8s  %s\n' "NAME" "DATE" "SIZE" "MEDIA"
    printf '%-30s %-22s %8s  %s\n' "----" "----" "----" "-----"

    # List .tar.gz files sorted by mtime, newest first
    for f in $(ls -t "$BACKUPDIR"/*.tar.gz 2>/dev/null); do
        local meta name created_at has_media size
        size=$(ls -lh "$f" | awk '{print $5}')

        # Try to extract snapshot.json from the archive
        meta=$(tar -xzf "$f" -O ./snapshot.json 2>/dev/null) || meta=""

        if [[ -n "$meta" ]]; then
            name=$(echo "$meta" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])" 2>/dev/null) || name="?"
            created_at=$(echo "$meta" | python3 -c "import sys,json; print(json.load(sys.stdin)['created_at'])" 2>/dev/null) || created_at="?"
            has_media=$(echo "$meta" | python3 -c "import sys,json; print('yes' if json.load(sys.stdin).get('has_media') else 'no')" 2>/dev/null) || has_media="?"
        else
            # Fallback: use filename and file attributes
            name=$(basename "$f" .tar.gz)
            created_at="?"
            has_media="?"
            log "  Warning: could not read metadata from $(basename "$f")"
        fi

        # Format created_at for display (replace T and Z)
        if [[ "$created_at" != "?" ]]; then
            created_at=$(echo "$created_at" | sed 's/T/ /;s/Z//')
        fi

        printf '%-30s %-22s %8s  %s\n' "$name" "$created_at" "$size" "$has_media"
    done
}

resolve_snapshot() {
    # Resolve a snapshot name/filename to a .tar.gz path in $BACKUPDIR.
    # Sets RESOLVED_SNAPSHOT to the path, or fails with an error.
    local name="$1"

    if [[ ! -d "$BACKUPDIR" ]]; then
        fail "Snapshot not found: $name (no backups directory). Run '$0 snapshot list'."
    fi

    # Exact match
    if [[ -f "$BACKUPDIR/${name}.tar.gz" ]]; then
        RESOLVED_SNAPSHOT="$BACKUPDIR/${name}.tar.gz"
        return 0
    fi

    # Prefix match — pick most recent (ls -t sorts by mtime)
    local matches
    matches=$(ls -t "$BACKUPDIR"/${name}*.tar.gz 2>/dev/null || true)
    if [[ -n "$matches" ]]; then
        RESOLVED_SNAPSHOT=$(echo "$matches" | head -1)
        return 0
    fi

    fail "Snapshot not found: $name. Run '$0 snapshot list' to see available snapshots."
}

snapshot_load() {
    local force=false
    local name=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force|-f) force=true; shift ;;
            -*) fail "Unknown option for snapshot load: $1" ;;
            *)
                if [[ -z "$name" ]]; then
                    name="$1"; shift
                else
                    fail "Usage: $0 snapshot load <name> [--force]"
                fi
                ;;
        esac
    done
    if [[ -z "$name" ]]; then
        fail "Usage: $0 snapshot load <name> [--force]"
    fi

    resolve_snapshot "$name"
    local snapshot_file="$RESOLVED_SNAPSHOT"
    log "Loading snapshot: $(basename "$snapshot_file")"

    # Pre-flight: PG must be running
    require_pg_running

    # Stop app services for clean restore
    log "Stopping app services for clean restore..."
    kill_pidfile "$PIDFILE_MCP"
    kill_pidfile "$PIDFILE_INGESTION"
    kill_port "$MCP_PORT"
    kill_port "$INGESTION_PORT"

    # Extract archive to temp dir
    local tmpdir
    tmpdir=$(mktemp -d)

    tar -xzf "$snapshot_file" -C "$tmpdir"

    # Restore DB
    log "Restoring database..."
    gunzip -c "$tmpdir/db.sql.gz" | \
        docker compose -f "$COMPOSE_FILE" exec -T \
            -e PGPASSWORD=neocortex postgres \
            psql -U neocortex -d neocortex >/dev/null 2>&1

    # Restore media (if present in snapshot)
    if [[ -d "$tmpdir/media_store" ]]; then
        log "Restoring media store..."
        rm -rf "$MEDIA_STORE"
        cp -r "$tmpdir/media_store" "$MEDIA_STORE"
        ok "Media store restored"
    fi

    # Cleanup
    rm -rf "$tmpdir"

    ok "Snapshot loaded: $(basename "$snapshot_file")"
    echo "  Run '$0 start' to bring services back up."
}

snapshot_delete() {
    local yes=false
    local name=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes|-y) yes=true; shift ;;
            -*) fail "Unknown option for snapshot delete: $1" ;;
            *)
                if [[ -z "$name" ]]; then
                    name="$1"; shift
                else
                    fail "Usage: $0 snapshot delete <name> [--yes]"
                fi
                ;;
        esac
    done
    if [[ -z "$name" ]]; then
        fail "Usage: $0 snapshot delete <name> [--yes]"
    fi

    resolve_snapshot "$name"
    local snapshot_file="$RESOLVED_SNAPSHOT"
    local size
    size=$(ls -lh "$snapshot_file" | awk '{print $5}')

    if ! $yes; then
        printf 'Delete snapshot "%s" (%s)? [y/N] ' "$(basename "$snapshot_file" .tar.gz)" "$size"
        local reply
        read -r reply
        case "$reply" in
            [yY]|[yY][eE][sS]) ;;
            *) log "Cancelled."; return 0 ;;
        esac
    fi

    rm -f "$snapshot_file"
    ok "Deleted: $(basename "$snapshot_file")"
}

do_status() {
    log "Service status:"
    # PostgreSQL
    if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U neocortex -d neocortex >/dev/null 2>&1; then
        ok "  PostgreSQL:  running"
    else
        log "  PostgreSQL:  stopped"
    fi
    # MCP
    if [[ -f "$PIDFILE_MCP" ]] && kill -0 "$(cat "$PIDFILE_MCP")" 2>/dev/null; then
        ok "  MCP server:  running (PID $(cat "$PIDFILE_MCP"), port $MCP_PORT)"
    else
        log "  MCP server:  stopped"
    fi
    # Ingestion
    if [[ -f "$PIDFILE_INGESTION" ]] && kill -0 "$(cat "$PIDFILE_INGESTION")" 2>/dev/null; then
        ok "  Ingestion:   running (PID $(cat "$PIDFILE_INGESTION"), port $INGESTION_PORT)"
    else
        log "  Ingestion:   stopped"
    fi
    # Logs
    log "  Logs:        $LOGDIR/"
    # Snapshots
    local snap_count=0
    if [[ -d "$BACKUPDIR" ]]; then
        snap_count=$(find "$BACKUPDIR" -name '*.tar.gz' 2>/dev/null | wc -l | tr -d ' ')
    fi
    log "  Snapshots:   $snap_count saved in $BACKUPDIR/"
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  start [--fresh]           Start services (persist data by default)
  stop                      Stop MCP + ingestion (PostgreSQL keeps running)
  stop --all                Stop everything including PostgreSQL
  status                    Show running services and DB info
  snapshot save <name>      Save current DB + media to a backup
  snapshot list             List saved snapshots
  snapshot load <name>      Restore DB + media from a snapshot
  snapshot delete <name>    Delete a saved snapshot

Environment:
  MCP_PORT=8000   INGESTION_PORT=8001   MAX_WAIT=60
EOF
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

CMD="${1:-help}"
shift || true
case "$CMD" in
    start)    do_start "$@" ;;
    stop)     do_stop "$@" ;;
    snapshot) do_snapshot "$@" ;;
    status)   do_status ;;
    help|-h|--help) usage ;;
    *)        fail "Unknown command: $CMD. Run '$0 help'." ;;
esac
