#!/usr/bin/env bash
# Is the backtest still running, and what does it say? Safe to run anytime.
if pgrep -f "scanner.backtest" >/dev/null 2>&1; then
  echo "STATUS: RUNNING. Latest progress:"
  tail -4 ~/bt.log
else
  echo "STATUS: NOT RUNNING (finished, or not started). Last 90 lines / summary:"
  tail -90 ~/bt.log
fi
