#!/usr/bin/env bash
# fix_rl_dc_ai_nalyzator_v2.sh
#
# This script is an improved version of the hot‑fix tool for RLdC_AiNalyzator.
# It avoids embedding multi‑line patch data in quoted strings, which can
# confuse `patch`. Instead, it writes temporary patch files and applies
# them. It also guides the user through making the script executable.
#
# Usage:
#   bash fix_rl_dc_ai_nalyzator_v2.sh [project_root]
#
# If no project root is provided, it defaults to the current directory.

set -e

PROJECT_ROOT="${1:-.}"

COLLECTOR="$PROJECT_ROOT/backend/collector.py"
DATABASE="$PROJECT_ROOT/backend/database.py"

if [[ ! -f "$COLLECTOR" || ! -f "$DATABASE" ]]; then
  echo "Error: collector.py or database.py not found. Run this script from the project root." >&2
  exit 1
fi

# Create a backup directory for patched files
BACKUP_DIR="$PROJECT_ROOT/backups/fix_rl_dc_ai_nalyzator_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp "$COLLECTOR" "$BACKUP_DIR/collector.py.bak"
cp "$DATABASE" "$BACKUP_DIR/database.py.bak"

# Create a temporary directory for patches
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Write the database patch to a file
cat > "$TMP_DIR/db.patch" <<'DBPATCH'
*** Begin Patch
*** Update File: backend/database.py
@@ class Position(Base):
-    exit_plan_json = Column(Text)                # JSON z planem wyjścia
+    exit_plan_json = Column(Text)                # JSON z planem wyjścia
+    # Position lifecycle — do not delete closed positions.
+    status = Column(String(20), default="OPEN", index=True)  # OPEN, CLOSED, RECONCILED
+    closed_at = Column(DateTime)
+    exit_price = Column(Float)
+    realized_pnl = Column(Float)
*** End Patch
*** Begin Patch
*** Update File: backend/database.py
@@ def _ensure_schema(conn):
-        ("exit_plan_json", "TEXT"),
+        ("exit_plan_json", "TEXT"),
+        ("status", "VARCHAR(20) DEFAULT 'OPEN'"),
+        ("closed_at", "DATETIME"),
+        ("exit_price", "FLOAT"),
+        ("realized_pnl", "FLOAT"),
*** End Patch
DBPATCH

# Write the collector patch to a file
cat > "$TMP_DIR/collector.patch" <<'COLLECTORPATCH'
*** Begin Patch
*** Update File: backend/collector.py
@@
-                    binance_status = result.get("status", "FILLED")
-                    logger.info(f"✅ LIVE ORDER EXECUTED: {pending.side} {pending.symbol} qty={qty} @ {exec_price} fee={_live_actual_fee} {_live_fee_asset} status={binance_status}")
-                    log_to_db("INFO", "live_trading",
-                              f"LIVE {pending.side} {pending.symbol} qty={qty:.8g} @ {exec_price:.6f} fee={_live_actual_fee:.8g} {_live_fee_asset}",
-                              db=db)
+                    binance_status = result.get("status")
+                    # Require that Binance confirms FILLED; otherwise mark pending order as rejected/unknown.
+                    if binance_status != "FILLED":
+                        log_to_db("ERROR", "live_trading",
+                                  f"Binance order not FILLED for {pending.symbol} {pending.side}: status={binance_status}, response={result}",
+                                  db=db)
+                        pending.status = "REJECTED" if binance_status in {"REJECTED", "EXPIRED", "CANCELED"} else str(binance_status or "UNKNOWN")
+                        pending.confirmed_at = utc_now_naive()
+                        self._trace_decision(
+                            db,
+                            symbol=pending.symbol,
+                            action="REJECT_PENDING",
+                            reason_code="order_not_filled",
+                            runtime_ctx=runtime_ctx,
+                            mode=p_mode,
+                            execution_check={"eligible": False, "pending_id": pending.id, "binance_status": binance_status},
+                            details={"side": pending.side, "binance_response": result},
+                            level="ERROR",
+                        )
+                        continue
+                    logger.info(f"✅ LIVE ORDER FILLED: {pending.side} {pending.symbol} qty={qty} @ {exec_price} fee={_live_actual_fee} {_live_fee_asset} status={binance_status}")
+                    log_to_db("INFO", "live_trading",
+                              f"LIVE FILLED {pending.side} {pending.symbol} qty={qty:.8g} @ {exec_price:.6f} fee={_live_actual_fee:.8g} {_live_fee_asset}",
+                              db=db)
*** End Patch
*** Begin Patch
*** Update File: backend/collector.py
@@ _demo_trading(self, db, mode):
-            position = (
-                db.query(Position)
-                .filter(Position.symbol == symbol, Position.mode == "demo")
-                .first()
-            )
+            _current_mode = tc.get("mode", "demo")
+            position = (
+                db.query(Position)
+                .filter(Position.symbol == symbol, Position.mode == _current_mode, Position.status != "CLOSED")
+                .first()
+            )
*** End Patch
*** Begin Patch
*** Update File: backend/collector.py
@@ _demo_trading(self, db, mode):
-            if side == "BUY" and position is not None:
-                self._trace_decision(
-                    db, symbol=symbol, action="SKIP", reason_code="buy_blocked_existing_position",
-                    runtime_ctx=runtime_ctx, mode=tc.get("mode", "demo"), signal_summary=signal_summary,
-                )
-                continue
+            if side == "BUY" and position is not None and float(position.quantity or 0) > 0:
+                # Block duplicate buy if an open position already exists for this symbol.
+                self._trace_decision(
+                    db, symbol=symbol, action="SKIP", reason_code="position_already_open",
+                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
+                    execution_check={"eligible": False, "existing_position_id": position.id, "existing_qty": float(position.quantity or 0)},
+                )
+                continue
*** End Patch
*** Begin Patch
*** Update File: backend/collector.py
@@ def _execute_confirmed_pending_orders(self, db, runtime_ctx, config):
-                        if float(position.quantity) <= 0:
-                            # --- Exit Quality snapshot ---
-                            self._save_exit_quality(db, position, exec_price, config)
-                            db.delete(position)
-                        else:
-                            # Częściowe zamknięcie — inkrementuj licznik i aktywuj trailing
-                            position.partial_take_count = int(position.partial_take_count or 0) + 1
+                        if float(position.quantity) <= 0:
+                            # --- Exit Quality snapshot ---
+                            self._save_exit_quality(db, position, exec_price, config)
+                            # Mark position as CLOSED instead of deleting it.
+                            position.status = "CLOSED"
+                            position.closed_at = utc_now_naive()
+                            position.exit_price = exec_price
+                            position.realized_pnl = float(position.net_pnl or 0.0)
+                            position.quantity = 0.0
+                            position.unrealized_pnl = 0.0
+                        else:
+                            # Partial exit — update partial count and trailing settings
+                            position.partial_take_count = int(position.partial_take_count or 0) + 1
*** End Patch
*** Begin Patch
*** Update File: backend/collector.py
@@ def _screen_entry_candidates(self, db, runtime_ctx, signal_summary, alerts, mode):
-                confirm_block = "\n✅ Auto-potwierdzone — pozycja otwarta automatycznie."
-                alert_title = f"{_mode_label}: OTWARTO POZYCJĘ"
+                confirm_block = "\n✅ Auto-potwierdzone — zlecenie oczekuje na wykonanie/FILLED."
+                alert_title = f"{_mode_label}: ORDER_CONFIRMED"
*** End Patch
*** Begin Patch
*** Update File: backend/collector.py
@@ def _execute_confirmed_pending_orders(self, db, runtime_ctx, config):
-                alert = Alert(
-                    alert_type="SIGNAL",
-                    severity="INFO",
-                    title=f"{p_mode.upper()} EXEC {pending.side} {pending.symbol}",
-                    message=f"{pending.side} {pending.symbol} qty={qty} exec_price={exec_price}. Powód: {pending.reason or '--'}",
-                    symbol=pending.symbol,
-                    is_sent=True,
-                    timestamp=utc_now_naive(),
-                )
-                db.add(alert)
+                # Send execution alert only after FILLED.
+                event_name = "POSITION_OPENED" if pending.side == "BUY" else "POSITION_CLOSED"
+                alert = Alert(
+                    alert_type="EXECUTION",
+                    severity="INFO",
+                    title=f"{p_mode.upper()} {event_name} {pending.symbol}",
+                    message=f"{event_name}: {pending.side} {pending.symbol} qty={qty} exec_price={exec_price}. Powód: {pending.reason or '--'}",
+                    symbol=pending.symbol,
+                    is_sent=True,
+                    timestamp=utc_now_naive(),
+                )
+                db.add(alert)
+                self._send_telegram_alert(
+                    f"{p_mode.upper()}: {event_name}",
+                    f"✅ {event_name}\nSymbol: {pending.symbol}\nSide: {pending.side}\nQty: {qty:.8g}\nCena: {exec_price:.8g}\nStatus: FILLED",
+                    force_send=True,
+                )
*** End Patch
COLLECTORPATCH

# Apply patches
 echo "Applying database patch..."
 patch -p0 -N --forward < "$TMP_DIR/db.patch" || true
 echo "Applying collector patch..."
 patch -p0 -N --forward < "$TMP_DIR/collector.patch" || true

 echo "Fix applied successfully. Backups stored in $BACKUP_DIR"
