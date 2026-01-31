"""
Data Collector - zbiera dane z Binance i zapisuje do bazy
Uruchamiany jako osobny proces w tle
"""
import os
import time
from datetime import datetime
from typing import List
from dotenv import load_dotenv
import logging
from sqlalchemy.orm import Session

from backend.database import SessionLocal, MarketData, Kline
from backend.binance_client import get_binance_client

load_dotenv()

# Konfiguracja loggera
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataCollector:
    """Kolektor danych rynkowych z Binance"""
    
    def __init__(self):
        """Inicjalizacja kolektora"""
        self.binance = get_binance_client()
        self.watchlist = self._load_watchlist()
        self.interval = int(os.getenv("COLLECTION_INTERVAL_SECONDS", 60))
        self.kline_timeframes = os.getenv("KLINE_TIMEFRAMES", "1m,1h").split(",")
        self.running = False
        
        logger.info(f"📊 DataCollector initialized")
        logger.info(f"   Watchlist: {', '.join(self.watchlist)}")
        logger.info(f"   Interval: {self.interval}s")
        logger.info(f"   Timeframes: {', '.join(self.kline_timeframes)}")
    
    def _load_watchlist(self) -> List[str]:
        """Wczytaj listę symboli do śledzenia"""
        watchlist_str = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT,MATICUSDT")
        return [s.strip() for s in watchlist_str.split(",")]
    
    def collect_market_data(self, db: Session):
        """
        Zbierz dane rynkowe (ticker prices) dla watchlist
        
        Args:
            db: Sesja bazy danych
        """
        logger.info("📊 Collecting market data...")
        
        for symbol in self.watchlist:
            try:
                # Pobierz 24h ticker
                ticker = self.binance.get_24hr_ticker(symbol)
                
                if ticker:
                    # Zapisz do bazy
                    market_data = MarketData(
                        symbol=symbol,
                        price=ticker["last_price"],
                        volume=ticker["volume"],
                        bid=ticker["bid_price"],
                        ask=ticker["ask_price"],
                        timestamp=datetime.utcnow()
                    )
                    db.add(market_data)
                    
                    logger.info(f"✅ {symbol}: ${ticker['last_price']:.2f} "
                              f"({ticker['price_change_percent']:+.2f}%)")
                else:
                    logger.warning(f"⚠️  Failed to get ticker for {symbol}")
                
                # Rate limiting - nie bombardujemy API
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"❌ Error collecting data for {symbol}: {str(e)}")
        
        try:
            db.commit()
            logger.info("✅ Market data committed to database")
        except Exception as e:
            logger.error(f"❌ Error committing market data: {str(e)}")
            db.rollback()
    
    def collect_klines(self, db: Session):
        """
        Zbierz dane świecowe (klines) dla watchlist
        
        Args:
            db: Sesja bazy danych
        """
        logger.info("📈 Collecting klines...")
        
        for symbol in self.watchlist:
            for timeframe in self.kline_timeframes:
                try:
                    # Pobierz ostatnie 100 świec
                    klines = self.binance.get_klines(symbol, timeframe, limit=100)
                    
                    if klines:
                        saved_count = 0
                        for k in klines:
                            # Sprawdź czy już istnieje (unikamy duplikatów)
                            open_time = datetime.fromtimestamp(k["open_time"] / 1000)
                            close_time = datetime.fromtimestamp(k["close_time"] / 1000)
                            
                            existing = db.query(Kline).filter(
                                Kline.symbol == symbol,
                                Kline.timeframe == timeframe,
                                Kline.open_time == open_time
                            ).first()
                            
                            if not existing:
                                kline = Kline(
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    open_time=open_time,
                                    close_time=close_time,
                                    open=k["open"],
                                    high=k["high"],
                                    low=k["low"],
                                    close=k["close"],
                                    volume=k["volume"],
                                    quote_volume=k["quote_volume"],
                                    trades=k["trades"],
                                    taker_buy_base=k["taker_buy_base"],
                                    taker_buy_quote=k["taker_buy_quote"]
                                )
                                db.add(kline)
                                saved_count += 1
                        
                        if saved_count > 0:
                            logger.info(f"✅ {symbol} {timeframe}: saved {saved_count} new klines")
                    else:
                        logger.warning(f"⚠️  Failed to get klines for {symbol} {timeframe}")
                    
                    # Rate limiting
                    time.sleep(0.2)
                    
                except Exception as e:
                    logger.error(f"❌ Error collecting klines for {symbol} {timeframe}: {str(e)}")
        
        try:
            db.commit()
            logger.info("✅ Klines committed to database")
        except Exception as e:
            logger.error(f"❌ Error committing klines: {str(e)}")
            db.rollback()
    
    def run_once(self):
        """Wykonaj jeden cykl zbierania danych"""
        logger.info("🔄 Starting data collection cycle...")
        
        db = SessionLocal()
        try:
            # Zbierz dane rynkowe
            self.collect_market_data(db)
            
            # Zbierz świece
            self.collect_klines(db)
            
            logger.info("✅ Collection cycle completed")
        except Exception as e:
            logger.error(f"❌ Error in collection cycle: {str(e)}")
        finally:
            db.close()
    
    def start(self):
        """Uruchom kolektor w pętli"""
        self.running = True
        logger.info("🚀 DataCollector started")
        
        while self.running:
            try:
                self.run_once()
                
                # Czekaj do następnego cyklu
                logger.info(f"⏰ Next collection in {self.interval} seconds...")
                time.sleep(self.interval)
                
            except KeyboardInterrupt:
                logger.info("⚠️  Keyboard interrupt received")
                self.stop()
            except Exception as e:
                logger.error(f"❌ Unexpected error in collector loop: {str(e)}")
                time.sleep(5)  # Krótka pauza przed ponowną próbą
    
    def stop(self):
        """Zatrzymaj kolektor"""
        self.running = False
        logger.info("🛑 DataCollector stopped")


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("RLdC Trading Bot - Data Collector")
    logger.info("=" * 60)
    
    collector = DataCollector()
    
    try:
        collector.start()
    except Exception as e:
        logger.error(f"❌ Fatal error: {str(e)}")
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
