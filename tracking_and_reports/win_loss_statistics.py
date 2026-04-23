from __future__ import annotations

from typing import Any

from services.win_loss_calculator import WinLossCalculator


class WinLossStatistics:
    def __init__(self, win_loss_calculator: WinLossCalculator):
        self.win_loss_calculator = win_loss_calculator

    def get_win_loss_ratio(self, session_id: int) -> dict[str, Any]:
        statistics = self.win_loss_calculator.calculate_win_loss_statistics(session_id)
        return {
            "session_id": session_id,
            "total_wins": statistics["total_wins"],
            "total_losses": statistics["total_losses"],
            "total_pushes": statistics["total_pushes"],
            "win_loss_ratio": statistics["win_loss_ratio"],
            "win_rate_percent": statistics["win_rate_percent"],
        }

    def get_performance_metrics(self, session_id: int) -> dict[str, Any]:
        statistics = self.win_loss_calculator.calculate_win_loss_statistics(session_id)
        return {
            "session_id": session_id,
            "roi_percent": statistics["roi_percent"],
            "profit_factor": statistics["profit_factor"],
            "net_profit": statistics["net_profit"],
            "total_staked": statistics["total_staked"],
            "longest_win_streak": statistics["longest_win_streak"],
            "longest_loss_streak": statistics["longest_loss_streak"],
        }

    def get_running_totals_by_game_index(self, session_id: int) -> dict[str, Any]:
        running_totals = self.win_loss_calculator.running_totals_by_game_index(session_id)
        return {
            "session_id": session_id,
            "running_totals_by_game_index": running_totals,
            "games_count": len(running_totals),
        }

    def get_full_win_loss_report(self, session_id: int) -> dict[str, Any]:
        statistics = self.win_loss_calculator.calculate_win_loss_statistics(session_id)
        running_totals = self.win_loss_calculator.running_totals_by_game_index(session_id)
        return {
            "session_id": session_id,
            "summary": statistics,
            "running_totals_by_game_index": running_totals,
            "games_count": len(running_totals),
        }
