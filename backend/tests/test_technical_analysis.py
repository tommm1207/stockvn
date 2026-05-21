import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from technical_analysis import calculate_macd, calculate_rsi, calculate_bollinger, analyze_stock

@pytest.fixture
def sample_data():
    """Tạo dữ liệu OHLCV giả lập cho 100 phiên."""
    dates = pd.date_range(end=datetime.now(), periods=100)
    data = []
    price = 100000
    for i, d in enumerate(dates):
        # Tạo xu hướng tăng nhẹ rồi giảm
        if i < 50:
            price += 500
        else:
            price -= 300
        
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": price - 200,
            "high": price + 500,
            "low": price - 500,
            "close": price,
            "volume": 1000000 + (i * 10000)
        })
    return data

def test_calculate_macd(sample_data):
    closes = np.array([x['close'] for x in sample_data])
    macd = calculate_macd(closes)
    
    assert 'macd' in macd
    assert 'signal' in macd
    assert 'histogram' in macd
    assert 'cross' in macd
    assert macd['cross'] in ['bullish', 'bearish', 'none']

def test_calculate_rsi(sample_data):
    closes = np.array([x['close'] for x in sample_data])
    rsi = calculate_rsi(closes)
    
    assert isinstance(rsi, float)
    assert 0 <= rsi <= 100

def test_calculate_bollinger(sample_data):
    closes = np.array([x['close'] for x in sample_data])
    bb = calculate_bollinger(closes)
    
    assert 'upper' in bb
    assert 'middle' in bb
    assert 'lower' in bb
    assert 'position' in bb
    assert bb['position'] in ['above_upper', 'upper_half', 'lower_half', 'below_lower', 'middle']

def test_full_analysis(sample_data):
    analysis = analyze_stock(sample_data)
    
    assert 'indicators' in analysis
    assert 'score' in analysis
    assert 'recommendation' in analysis
    assert analysis['recommendation'] in ['BUY', 'SELL', 'HOLD']
    
    inds = analysis['indicators']
    assert 'rsi' in inds
    assert 'macd' in inds
    assert 'bollinger' in inds
    assert 'ma20' in inds
    assert 'ma50' in inds
    assert 'volume' in inds
