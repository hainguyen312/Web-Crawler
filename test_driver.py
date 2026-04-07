from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

options = webdriver.ChromeOptions()
options.add_argument("--no-first-run")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)
time.sleep(2)
print("URL:", driver.current_url)
driver.get("https://shopee.vn")
time.sleep(3)
print("Shopee:", driver.current_url)
driver.quit()