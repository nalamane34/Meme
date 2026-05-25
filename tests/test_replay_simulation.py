from scripts.build_replay import _simulate_outcome


def test_take_profit_hit():
    prices = [1.0, 1.5, 2.5, 4.0]  # 4x — way past 200% TP
    o = _simulate_outcome(prices, stop_loss=0.25, take_profit=2.0, trail=0.35)
    assert o >= 2.0


def test_stop_loss_hit():
    prices = [1.0, 0.9, 0.7]
    o = _simulate_outcome(prices, stop_loss=0.25, take_profit=2.0, trail=0.35)
    assert o <= -0.25 + 1e-9


def test_trailing_stop_hit():
    prices = [1.0, 1.5, 1.6, 1.0]  # peaks at 1.6, falls to 1.0 = -37% from peak
    o = _simulate_outcome(prices, stop_loss=0.25, take_profit=2.0, trail=0.35)
    # exited at 1.0, so outcome = 0
    assert abs(o - 0.0) < 1e-9


def test_no_exit_returns_final_pnl():
    prices = [1.0, 1.1, 1.2]
    o = _simulate_outcome(prices, stop_loss=0.25, take_profit=2.0, trail=0.35)
    assert abs(o - 0.2) < 1e-9
