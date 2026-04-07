# Web Crawler API

FastAPI endpoints để crawl dữ liệu từ Pinterest, Shopee và Tiki.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy API Server

```bash
# Chạy trực tiếp
python api.py

# Hoặc dùng uvicorn
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

API sẽ chạy tại: `http://localhost:8000`

Documentation tự động tại: `http://localhost:8000/docs`

## Endpoints

### 1. Pinterest Search

**POST** `/api/pinterest/search`

Crawl ảnh từ Pinterest theo từ khóa.

**Request Body:**
```json
{
  "keyword": "sunset beach",
  "max_images": 20,
  "max_pages": 30,
  "email": "your_email@example.com",  // Tùy chọn
  "password": "your_password",         // Tùy chọn
  "headless": true,
  "debug": false,
  "cookies_path": "cookies.pkl"
}
```

**Response:**
```json
{
  "keyword": "sunset beach",
  "total": 20,
  "images": [
    "https://i.pinimg.com/originals/...",
    "https://i.pinimg.com/originals/..."
  ],
  "message": "Thành công"
}
```

### 2. Shopee Search

**POST** `/api/shopee/search`

Crawl sản phẩm từ Shopee theo từ khóa.

**⚠️ QUAN TRỌNG**: 
- **Nếu đã có cookie** (`~/.shopee_cookies.json`): Có thể dùng API ngay với `headless=True`, không cần đăng nhập lại
- **Nếu chưa có cookie**: Phải chạy script `shopeeCrawler.py` trực tiếp lần đầu để đăng nhập (cookie sẽ được lưu tự động)
- **Kiểm tra cookie**: Chạy `ls ~/.shopee_cookies.json` để xem đã có cookie chưa

**Request Body:**
```json
{
  "keyword": "điện thoại",
  "max_items": 30,
  "headless": true,
  "debug": false,
  "relogin": false
}
```

**Response:**
```json
{
  "keyword": "điện thoại",
  "total": 30,
  "products": [
    {
      "image_url": "https://cf.shopee.vn/file/...",
      "product_url": "https://shopee.vn/..."
    }
  ],
  "message": "Thành công"
}
```

### 3. Tiki Search

**POST** `/api/tiki/search`

Crawl sản phẩm từ Tiki theo từ khóa.

**⚠️ QUAN TRỌNG**: 
- **Nếu đã có cookie** (`~/.tiki_cookies.json`): Có thể dùng API ngay với `headless=True`, không cần đăng nhập lại
- **Nếu chưa có cookie**: Phải chạy script `tikiCrawler.py` trực tiếp lần đầu để đăng nhập (cookie sẽ được lưu tự động)
- **Kiểm tra cookie**: Chạy `ls ~/.tiki_cookies.json` để xem đã có cookie chưa

**Request Body:**
```json
{
  "keyword": "laptop",
  "max_items": 30,
  "headless": true,
  "debug": false,
  "relogin": false
}
```

**Response:**
```json
{
  "keyword": "laptop",
  "total": 30,
  "products": [
    {
      "image_url": "https://salt.tikicdn.com/...",
      "product_url": "https://tiki.vn/..."
    }
  ],
  "message": "Thành công"
}
```

## Ví dụ sử dụng với cURL

### Pinterest
```bash
curl -X POST "http://localhost:8000/api/pinterest/search" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword": "sunset beach",
    "max_images": 10,
    "headless": true
  }'
```

### Shopee
```bash
curl -X POST "http://localhost:8000/api/shopee/search" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword": "điện thoại",
    "max_items": 20,
    "headless": false
  }'
```

### Tiki
```bash
curl -X POST "http://localhost:8000/api/tiki/search" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword": "laptop",
    "max_items": 20,
    "headless": false
  }'
```

## Ví dụ sử dụng với Python

```python
import requests

# Pinterest
response = requests.post(
    "http://localhost:8000/api/pinterest/search",
    json={
        "keyword": "sunset beach",
        "max_images": 10,
        "headless": True
    }
)
data = response.json()
print(f"Tìm thấy {data['total']} ảnh")

# Shopee
response = requests.post(
    "http://localhost:8000/api/shopee/search",
    json={
        "keyword": "điện thoại",
        "max_items": 20
    }
)
data = response.json()
for product in data['products']:
    print(f"Ảnh: {product['image_url']}")
    print(f"URL: {product['product_url']}")

# Tiki
response = requests.post(
    "http://localhost:8000/api/tiki/search",
    json={
        "keyword": "laptop",
        "max_items": 20
    }
)
data = response.json()
for product in data['products']:
    print(f"Ảnh: {product['image_url']}")
    print(f"URL: {product['product_url']}")
```

## Health Check

**GET** `/health`

Kiểm tra trạng thái API.

```bash
curl http://localhost:8000/health
```

## Lưu ý

1. **Shopee và Tiki - Kiểm tra cookie**:
   ```bash
   # Kiểm tra xem đã có cookie chưa
   ls ~/.shopee_cookies.json
   ls ~/.tiki_cookies.json
   
   # Nếu đã có cookie: Có thể dùng API ngay với headless=True
   # Nếu chưa có cookie: Chạy script trực tiếp lần đầu để đăng nhập
   python shopeeCrawler.py "điện thoại" --headless=false
   python tikiCrawler.py "laptop" --headless=false
   # Sau khi đăng nhập, cookie sẽ được lưu tự động
   ```

2. **Headless mode**: 
   - Khi `headless=True`, browser chạy ẩn
   - **Không thể đăng nhập thủ công trong headless mode**
   - Phải có cookie đã lưu trước khi dùng API với `headless=True`

3. **Lỗi thường gặp**:
   - `Không có cookie đã lưu`: Chạy script crawler trực tiếp lần đầu để đăng nhập (chỉ cần làm 1 lần)
   - `Không thể đăng nhập lại trong headless mode`: Dùng script crawler với `--relogin` để đăng nhập lại
   - `Cookie đã hết hạn`: Chạy lại script crawler để đăng nhập lại
   - **Nếu đã có cookie hợp lệ**: Không cần đăng nhập lại, API sẽ tự động dùng cookie

4. **Rate limiting**: API không có rate limiting tích hợp. Nên thêm middleware nếu cần.

5. **Concurrent requests**: API hỗ trợ nhiều request đồng thời nhưng mỗi crawler sẽ tốn thời gian (10-60 giây tùy số lượng).

6. **Error handling**: Tất cả lỗi sẽ trả về HTTP status code phù hợp với thông báo lỗi chi tiết.
