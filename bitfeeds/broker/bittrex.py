from bitfeeds.socket.restful import RESTfulApiSocket
from bitfeeds.exchange import ExchangeGateway
from bitfeeds.market import L2Depth, Trade
from bitfeeds.util import Logger
from bitfeeds.instrument import Instrument
from bitfeeds.storage.sql_template import SqlStorageTemplate
from functools import partial
from datetime import datetime
import threading
import time


class BittrexBroker(RESTfulApiSocket):
    """
    Exchange gateway RESTfulApi
    """
    def __init__(self):
        RESTfulApiSocket.__init__(self)
        
    @classmethod
    def get_trades_timestamp_field_name(cls):
        return 'TimeStamp'
        
    @classmethod
    def get_trades_timestamp_format(cls):
        return '%Y-%m-%dT%H:%M:%S.%f'
    
    @classmethod
    def get_bids_field_name(cls):
        return 'buy'
        
    @classmethod
    def get_asks_field_name(cls):
        return 'sell'
        
    @classmethod
    def get_price_field_name(cls):
        return "Rate"
        
    @classmethod
    def get_volume_field_name(cls):
        return "Quantity"
        
    @classmethod
    def get_trade_price_field_name(cls):
        return 'Price'        
        
    @classmethod
    def get_trade_volume_field_name(cls):
        return 'Quantity'   
        
    @classmethod
    def get_trade_side_field_name(cls):
        return 'OrderType'
        
    @classmethod
    def get_trade_id_field_name(cls):
        return 'Id'
        
    @classmethod
    def get_order_book_link(cls, instmt):
        return "https://bittrex.com/api/v1.1/public/getorderbook?market=%s&type=both&depth=5" % instmt.get_instmt_code()

    @classmethod
    def get_trades_link(cls, instmt):
        return "https://bittrex.com/api/v1.1/public/getmarkethistory?market=%s" % instmt.get_instmt_code()
                
    @classmethod
    def parse_l2_depth(cls, instmt, raw):
        """
        Parse raw data to L2 depth
        :param instmt: Instrument
        :param raw: Raw data in JSON
        """
        l2_depth = L2Depth()
        raw = raw["result"]
        keys = list(raw.keys())
        if cls.get_bids_field_name() in keys and \
           cls.get_asks_field_name() in keys:
            
            # Date time
            l2_depth.date_time = datetime.utcnow().strftime("%Y%m%d %H:%M:%S.%f")
            
            # Bids
            bids = raw[cls.get_bids_field_name()]
            for i in range(0, 5):
                l2_depth.bids[i].price = bids[i][cls.get_price_field_name()]
                l2_depth.bids[i].volume = bids[i][cls.get_volume_field_name()]
                
            # Asks
            asks = raw[cls.get_asks_field_name()]
            for i in range(0, 5):
                l2_depth.asks[i].price = asks[i][cls.get_price_field_name()]
                l2_depth.asks[i].volume = asks[i][cls.get_volume_field_name()]          
        else:
            raise Exception('Does not contain order book keys in instmt %s-%s.\nOriginal:\n%s' % \
                (instmt.get_exchange_name(), instmt.get_instmt_name(), \
                 raw))
        
        return l2_depth

    @classmethod
    def parse_trade(cls, instmt, raw):
        """
        :param instmt: Instrument
        :param raw: Raw data in JSON
        :return:
        """
        trade = Trade()
        keys = list(raw.keys())
        
        if cls.get_trades_timestamp_field_name() in keys and \
           cls.get_trade_id_field_name() in keys and \
           cls.get_trade_side_field_name() in keys and \
           cls.get_trade_price_field_name() in keys and \
           cls.get_trade_volume_field_name() in keys:
        
            # Date time
            date_time = raw[cls.get_trades_timestamp_field_name()]
            if len(date_time) == 19:
                date_time += '.'
            date_time += '0' * (26 - len(date_time))
            date_time = datetime.strptime(date_time, cls.get_trades_timestamp_format())
            trade.date_time = date_time.strftime("%Y%m%d %H:%M:%S.%f")      
            
            # Trade side
            trade.trade_side = 1 if raw[cls.get_trade_side_field_name()] == 'BUY' else 2
                
            # Trade id
            trade.trade_id = str(raw[cls.get_trade_id_field_name()])
            
            # Trade price
            trade.trade_price = float(str(raw[cls.get_trade_price_field_name()]))
            
            # Trade volume
            trade.trade_volume = float(str(raw[cls.get_trade_volume_field_name()]))
        else:
            raise Exception('Does not contain trade keys in instmt %s-%s.\nOriginal:\n%s' % \
                (instmt.get_exchange_name(), instmt.get_instmt_name(), \
                 raw))        

        return trade

    @classmethod
    def get_order_book(cls, instmt):
        """
        Get order book
        :param instmt: Instrument
        :return: Object L2Depth
        """
        res = cls.request(cls.get_order_book_link(instmt))
        if len(res) > 0:
            return cls.parse_l2_depth(instmt=instmt,
                                       raw=res)
        else:
            return None

    @classmethod
    def get_trades(cls, instmt):
        """
        Get trades
        :param instmt: Instrument
        :param trade_id: Trade id
        :return: List of trades
        """
        link = cls.get_trades_link(instmt)
        res = cls.request(link)
        res = res["result"]
        trades = []
        if len(res) > 0:
            for i in range(len(res)-1, -1, -1):
                trade = cls.parse_trade(instmt=instmt,
                                         raw=res[i])
                trades.append(trade)

        return trades


class ExchGwBittrex(ExchangeGateway):
    """
    Exchange gateway Bittrex
    """
    def __init__(self, db_storages):
        """
        Constructor
        :param db_storage: Database storage
        """
        ExchangeGateway.__init__(self, ExchGwApiBittrex(), db_storages)

    @classmethod
    def get_exchange_name(cls):
        """
        Get exchange name
        :return: Exchange name string
        """
        return 'Bittrex'

    def get_order_book_worker(self, instmt):
        """
        Get order book worker
        :param instmt: Instrument
        """
        while True:
            try:
                l2_depth = self.api_socket.get_order_book(instmt)
                if l2_depth is not None and l2_depth.is_diff(instmt.get_l2_depth()):
                    instmt.set_prev_l2_depth(instmt.get_l2_depth())
                    instmt.set_l2_depth(l2_depth)
                    instmt.incr_order_book_id()
                    self.insert_order_book(instmt)
            except Exception as e:
                Logger.error(self.__class__.__name__, "Error in order book: %s" % e)
            time.sleep(1)

    def get_trades_worker(self, instmt):
        """
        Get order book worker thread
        :param instmt: Instrument name
        """
        while True:
            try:
                ret = self.api_socket.get_trades(instmt)
                if ret is None or len(ret) == 0:
                    time.sleep(1)
                    continue
            except Exception as e:
                Logger.error(self.__class__.__name__, "Error in trades: %s" % e)                
                
            for trade in ret:
                assert isinstance(trade.trade_id, str), "trade.trade_id(%s) = %s" % (type(trade.trade_id), trade.trade_id)
                assert isinstance(instmt.get_exch_trade_id(), str), \
                       "instmt.get_exch_trade_id()(%s) = %s" % (type(instmt.get_exch_trade_id()), instmt.get_exch_trade_id())
                if int(trade.trade_id) > int(instmt.get_exch_trade_id()):
                    instmt.set_exch_trade_id(trade.trade_id)
                    instmt.incr_trade_id()
                    self.insert_trade(instmt, trade)
            
            # After the first time of getting the trade, indicate the instrument
            # is recovered
            if not instmt.get_recovered():
                instmt.set_recovered(True)

            time.sleep(1)

    def start(self, instmt):
        """
        Start the exchange gateway
        :param instmt: Instrument
        :return List of threads
        """
        instmt.set_l2_depth(L2Depth(5))
        instmt.set_prev_l2_depth(L2Depth(5))
        instmt.set_instmt_snapshot_table_name(self.get_instmt_snapshot_table_name(instmt.get_exchange_name(),
                                                                                  instmt.get_instmt_name()))
        self.init_instmt_snapshot_table(instmt)
        instmt.set_recovered(False)
        t1 = threading.Thread(target=partial(self.get_order_book_worker, instmt))
        t2 = threading.Thread(target=partial(self.get_trades_worker, instmt))
        t1.start()
        t2.start()
        return [t1, t2]
        
        
if __name__ == '__main__':
    Logger.init_log()
    exchange_name = 'Bittrex'
    instmt_name = 'BTCETH'
    instmt_code = 'BTC-ETH'
    instmt = Instrument(exchange_name, instmt_name, instmt_code)    
    db_storage = SqlStorageTemplate()
    exch = ExchGwBittrex([db_storage])
    instmt.set_l2_depth(L2Depth(5))
    instmt.set_prev_l2_depth(L2Depth(5))
    instmt.set_recovered(False)    
    # exch.get_order_book_worker(instmt)
    exch.get_trades_worker(instmt)
