"""
简易网格交易脚本（Binance Spot REST API）

特点：
- 使用 Binance Spot REST API（签名请求）实现下单/查询/撤单
- 从环境变量读取 API_KEY / API_SECRET；支持 TESTNET 切换
- 默认 dry-run 模式（只打印计划，不实际下单），避免误触发真实交易
- 支持按价格区间和网格数量计算均匀网格并下限价单（买在区间下方，卖在区间上方）

安全提示：
- 请通过环境变量设置 BINANCE_API_KEY 和 BINANCE_API_SECRET；不要将密钥写入代码或日志。
- 在真实交易前先用 dry-run=True 或在 Binance Testnet 上充分测试。

使用示例：
python BTC_Test.py --symbol BTCUSDT --min-price 56000 --max-price 60000 --grids 8 --total-qty 0.001 --dry-run

"""
import os
import time
import hmac
import hashlib
import requests
import argparse
from urllib.parse import urlencode

# ==================== 配置部分 ====================
# 从环境变量读取 API 密钥，确保安全性
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')

# 测试网络配置：当 USE_TESTNET=1 时使用 testnet 域名
# 测试网络用于开发和测试，不会产生真实交易
USE_TESTNET = os.environ.get('BINANCE_USE_TESTNET', '') in {'1', 'true', 'True'}

# 根据测试网络配置选择对应的 API 基础 URL
BASE_URL = 'https://testnet.binance.vision' if USE_TESTNET else 'https://api.binance.com'


def sign_params(params: dict, secret: str) -> str:
    """
    签名参数（HMAC SHA256），返回带签名的 query string
    
    步骤：
    1. 将参数字典转换为 URL 编码的查询字符串
    2. 使用 HMAC-SHA256 算法和 API 密钥对查询字符串进行签名
    3. 将签名附加到查询字符串末尾
    
    Binance API 要求所有私有接口请求都必须包含签名
    """
    # 1. 将参数字典转换为 URL 编码的查询字符串
    query = urlencode(params, doseq=True)
    
    # 2. 使用 HMAC-SHA256 算法生成签名
    #    - secret.encode('utf-8'): 将密钥转换为字节
    #    - query.encode('utf-8'): 将查询字符串转换为字节
    #    - hashlib.sha256: 使用 SHA256 哈希算法
    signature = hmac.new(secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha256).hexdigest()
    
    # 3. 返回带签名的完整查询字符串
    return f"{query}&signature={signature}"


def send_signed_request(method: str, path: str, params: dict, api_key: str, api_secret: str):
    """
    发送签名请求到 Binance API（同步请求）
    
    步骤：
    1. 复制参数并添加时间戳（防止重放攻击）
    2. 对参数进行签名
    3. 构建完整的请求 URL
    4. 设置 API 密钥头信息
    5. 根据请求方法发送 HTTP 请求
    6. 检查响应状态并返回 JSON 数据
    """
    # 1. 复制参数并添加时间戳（防止重放攻击）
    params = params.copy() if params else {}
    params['timestamp'] = int(time.time() * 1000)  # 毫秒级时间戳
    
    # 2. 对参数进行签名
    qs = sign_params(params, api_secret)
    
    # 3. 构建完整的请求 URL
    url = f"{BASE_URL}{path}?{qs}"
    
    # 4. 设置 API 密钥头信息
    headers = {'X-MBX-APIKEY': api_key}
    
    # 5. 根据请求方法发送 HTTP 请求
    if method.upper() == 'GET':
        r = requests.get(url, headers=headers, timeout=10)
    elif method.upper() == 'DELETE':
        r = requests.delete(url, headers=headers, timeout=10)
    else:
        r = requests.post(url, headers=headers, timeout=10)
    
    # 6. 检查响应状态并返回 JSON 数据
    r.raise_for_status()  # 如果状态码不是 200，抛出异常
    return r.json()


def send_public_request(path: str, params: dict = None):
    """
    发送公开请求到 Binance API（无需签名）
    
    用于获取公开数据，如价格、交易对信息等
    这些接口不需要 API 密钥和签名
    """
    # 构建请求 URL
    url = f"{BASE_URL}{path}"
    
    # 发送 GET 请求
    r = requests.get(url, params=params, timeout=10)
    
    # 检查响应状态
    r.raise_for_status()
    
    # 返回 JSON 格式的响应数据
    return r.json()


def get_symbol_price(symbol: str) -> float:
    """
    获取指定交易对的当前价格
    
    使用 Binance 的 /api/v3/ticker/price 接口
    返回交易对的当前最新价格
    """
    # 发送公开请求获取价格数据
    data = send_public_request('/api/v3/ticker/price', {'symbol': symbol})
    
    # 提取价格字段并转换为浮点数
    return float(data['price'])


def get_open_orders(symbol: str, api_key: str, api_secret: str):
    """
    获取指定交易对的所有未完成订单
    
    使用 Binance 的 /api/v3/openOrders 接口
    返回当前账户中该交易对的所有挂单信息
    """
    return send_signed_request('GET', '/api/v3/openOrders', {'symbol': symbol}, api_key, api_secret)


def cancel_order(symbol: str, orderId: int, api_key: str, api_secret: str):
    """
    取消指定订单
    
    使用 Binance 的 /api/v3/order 接口（DELETE 方法）
    根据订单 ID 取消指定的挂单
    """
    return send_signed_request('DELETE', '/api/v3/order', {'symbol': symbol, 'orderId': orderId}, api_key, api_secret)


def place_limit_order(symbol: str, side: str, quantity: float, price: float, api_key: str, api_secret: str, client_order_id: str = None):
    """
    下限价单
    
    使用 Binance 的 /api/v3/order 接口（POST 方法）
    创建指定价格和数量的限价单
    
    参数说明：
    - symbol: 交易对（如 BTCUSDT）
    - side: 买卖方向（BUY/SELL）
    - quantity: 交易数量
    - price: 限价价格
    - client_order_id: 自定义订单 ID（可选）
    """
    # 构建订单参数
    params = {
        'symbol': symbol,
        'side': side.upper(),  # 确保方向为大写
        'type': 'LIMIT',       # 限价单类型
        'timeInForce': 'GTC',  # 订单有效时间：Good Till Cancel（直到取消）
        'quantity': format(quantity, 'f'),  # 格式化数量，避免科学计数法
        'price': format(price, 'f')        # 格式化价格，避免科学计数法
    }
    
    # 如果提供了自定义订单 ID，添加到参数中
    if client_order_id:
        params['newClientOrderId'] = client_order_id
    
    # 发送下单请求
    return send_signed_request('POST', '/api/v3/order', params, api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


def compute_grid_prices(min_price: float, max_price: float, grids: int):
    """
    计算网格交易的价格点
    
    在最小价格和最大价格之间均匀分布指定数量的价格点
    用于网格交易的挂单价格计算
    
    例如：min_price=56000, max_price=60000, grids=5
    价格点：[56000, 57000, 58000, 59000, 60000]
    """
    # 验证网格数量必须大于等于2
    if grids < 2:
        raise ValueError('grids must be >= 2')
    
    # 计算价格步长：总价格区间除以（网格数-1）
    step = (max_price - min_price) / (grids - 1)
    
    # 生成均匀分布的价格点列表
    prices = [min_price + i * step for i in range(grids)]
    
    return prices


def cancel_existing_grid_orders(symbol: str, prefix: str = 'grid_py_', dry_run: bool = True):
    """
    取消当前账户中 clientOrderId 以 prefix 开头的挂单（仅针对指定 symbol）
    
    在创建新的网格订单前，先清理旧的网格订单，避免重复下单
    通过 clientOrderId 前缀识别网格订单
    """
    # 如果是 dry-run 模式，跳过实际取消操作
    if dry_run:
        print('[dry-run] skip cancelling existing grid orders')
        return
    
    try:
        # 1. 获取指定交易对的所有未完成订单
        orders = get_open_orders(symbol, BINANCE_API_KEY, BINANCE_API_SECRET)
        
        # 2. 遍历所有订单，找到以指定前缀开头的网格订单
        for o in orders:
            coid = o.get('clientOrderId') or o.get('clientOrderId', '')
            
            # 3. 如果订单的 clientOrderId 以指定前缀开头，则取消该订单
            if coid and coid.startswith(prefix):
                print(f'取消订单 {o.get("orderId")} (clientOrderId={coid})')
                cancel_order(symbol, int(o['orderId']), BINANCE_API_KEY, BINANCE_API_SECRET)
                
    except Exception as e:
        print(f'取消现有网格订单时出错：{e}')


def plan_and_place_grid(symbol: str, min_price: float, max_price: float, grids: int, total_qty: float = None, per_order_qty: float = None, dry_run: bool = True):
    """
    网格交易的核心函数：规划并执行网格下单
    
    步骤：
    1. 计算网格价格点
    2. 获取当前市场价格
    3. 计算每单交易数量
    4. 根据价格与当前价的关系确定买卖方向
    5. 显示交易计划
    6. 取消现有网格订单（非 dry-run 模式）
    7. 执行下单操作
    """
    # 1. 计算网格价格点
    prices = compute_grid_prices(min_price, max_price, grids)
    
    # 2. 获取当前市场价格
    current_price = get_symbol_price(symbol)
    print(f'当前价格: {current_price:.8f}')

    # 3. 计算每单交易数量
    if per_order_qty is None:
        if total_qty is None:
            raise ValueError('请提供 total_qty 或 per_order_qty')
        per_order_qty = total_qty / grids  # 将总数量均匀分配到每个网格

    # 4. 根据价格与当前价的关系确定买卖方向
    planned = []  # 存储计划订单的列表
    for p in prices:
        if p < current_price:
            side = 'BUY'   # 价格低于当前价，挂买单
        elif p > current_price:
            side = 'SELL'  # 价格高于当前价，挂卖单
        else:
            # 当前价则跳过，避免在当前价下单
            continue
        planned.append({'price': round(p, 8), 'side': side, 'qty': float(per_order_qty)})

    # 5. 显示交易计划
    print('计划下单：')
    for o in planned:
        print(f"  {o['side']} {symbol} qty={o['qty']} price={o['price']}")

    # 6. 取消已有网格订单（仅在非 dry-run 时）
    cancel_existing_grid_orders(symbol, prefix='grid_py_', dry_run=dry_run)

    # 7. 执行下单操作
    for idx, o in enumerate(planned, 1):
        # 生成唯一的客户端订单 ID（包含时间戳和序号）
        client_id = f'grid_py_{int(time.time())}_{idx}'
        
        if dry_run:
            # dry-run 模式：只打印计划，不实际下单
            print(f"[dry-run] would place {o['side']} {o['qty']} @ {o['price']} (clientOrderId={client_id})")
        else:
            # 实际下单模式
            try:
                res = place_limit_order(symbol, o['side'], o['qty'], o['price'], BINANCE_API_KEY, BINANCE_API_SECRET, client_order_id=client_id)
                print(f"下单成功: {res}")
            except Exception as e:
                print(f"下单失败: {e}")


def parse_args():
    """
    解析命令行参数
    
    定义脚本运行所需的参数，包括交易对、价格区间、网格数量等
    """
    p = argparse.ArgumentParser(description='简易网格交易（Binance Spot）')
    
    # 交易对参数，默认 BTCUSDT
    p.add_argument('--symbol', default='BTCUSDT', help='交易对符号，如 BTCUSDT, ETHUSDT')
    
    # 价格区间参数（必需）
    p.add_argument('--min-price', type=float, required=True, help='网格交易的最低价格')
    p.add_argument('--max-price', type=float, required=True, help='网格交易的最高价格')
    
    # 网格数量参数，默认5个网格
    p.add_argument('--grids', type=int, default=5, help='网格数量，在价格区间内均匀分布')
    
    # 交易数量参数（二选一）
    p.add_argument('--total-qty', type=float, default=None, help='网格总持仓量，按均匀分配到每个网格')
    p.add_argument('--per-order-qty', type=float, default=None, help='每个挂单的数量，优先级高于 total-qty')
    
    # 测试模式参数，默认启用 dry-run 模式
    p.add_argument('--dry-run', action='store_true', default=True, 
                   help='默认 dry-run，设置后不会下单（CLI 中传入 --dry-run 会使其为 True）')
    
    return p.parse_args()


def main():
    """
    主函数：程序入口点
    
    执行流程：
    1. 解析命令行参数
    2. 检查 API 密钥配置
    3. 调用网格交易核心函数
    """
    # 1. 解析命令行参数
    args = parse_args()

    # 2. 环境变量 API 密钥检查
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        print('警告：未检测到 BINANCE_API_KEY/BINANCE_API_SECRET，所有签名请求将无法执行；请通过环境变量注入。')

    # 3. 获取 dry-run 模式设置
    # argparse 中 --dry-run 默认值为 True，这里直接使用参数值
    dry_run = args.dry_run

    # 4. 调用网格交易核心函数
    plan_and_place_grid(
        symbol=args.symbol,
        min_price=args.min_price,
        max_price=args.max_price,
        grids=args.grids,
        total_qty=args.total_qty,
        per_order_qty=args.per_order_qty,
        dry_run=dry_run
    )


if __name__ == '__main__':
    main()