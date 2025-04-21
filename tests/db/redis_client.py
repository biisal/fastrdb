from redis.asyncio import Redis

redis_host = "localhost"           
redis_port = 6379          
redis_db = 0
redis_decode_responses = True 

redis_client = Redis(
    host=redis_host,
    port=redis_port,
    db=redis_db,
    decode_responses=redis_decode_responses
)
