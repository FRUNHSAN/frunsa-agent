# 系统架构

## 核心服务
- API Gateway (Kong): 统一入口，限流，认证
- User Service (Go): 用户注册登录，JWT 鉴权
- Order Service (Python): 订单创建，库存扣减，支付回调
- Search Service (Elasticsearch): 全文检索，商品搜索
