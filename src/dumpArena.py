import requests
import json
import time
import os
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

class WoWPvPLeaderboard:
    """WoW PvP 排行榜資料抓取類別"""
    
    def __init__(self, client_id: str, client_secret: str, region: str = 'us'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region
        self.access_token = None
        # Season 9+ 新增了 rbg (戰場排行榜)
        self.available_brackets = ['2v2', '3v3', '5v5', 'rbg']
        self.character_cache = {}  # 緩存角色詳情，避免重複請求
        
    def get_access_token(self) -> bool:
        """獲取 Battle.net API access token"""
        try:
            data = {'grant_type': 'client_credentials'}
            token_url = f'https://{self.region}.battle.net/oauth/token'
            
            response = requests.post(token_url, data=data, auth=(self.client_id, self.client_secret), timeout=30)
            
            if response.status_code != 200:
                print(f"✗ Token 請求失敗，狀態碼: {response.status_code}")
                print(f"錯誤內容: {response.text}")
                return False
                
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                print(f"✓ 成功獲取 access token")
                return True
            else:
                print(f"✗ 無法獲取 access token: {result}")
                return False
                
        except Exception as e:
            print(f"✗ 獲取 access token 時發生錯誤: {e}")
            return False

    def get_api_url(self, season: int, bracket: str) -> str:
        """根據賽季返回正確的 API URL"""
        base_url = "https://tw.api.blizzard.com/data/wow"
        
        if season >= 9:
            # Season 9+ 使用新的 API 結構
            return f"{base_url}/pvp-season/{season}/pvp-leaderboard/{bracket}"
        else:
            # Season 8- 使用舊的 API 結構
            return f"{base_url}/pvp-region/0/pvp-season/{season}/pvp-leaderboard/{bracket}"


    def fetch_character_details(self, realm_slug: str, character_name: str) -> Optional[Dict]:
        """獲取角色詳細信息（職業、種族等）"""
        # 檢查緩存
        lowercase_name = ''.join(c.lower() if 'A' <= c <= 'Z' else c for c in character_name)
        encoded_name = requests.utils.quote(lowercase_name)
        cache_key = f"{realm_slug}:{encoded_name}"
        if cache_key in self.character_cache:
            return self.character_cache[cache_key]
            
        if not self.access_token:
            return None
            
        try:
            # URL 編碼角色名稱
            #encoded_name = requests.utils.quote(character_name.lower())
            


            url = f"https://tw.api.blizzard.com/profile/wow/character/{realm_slug}/{encoded_name}"
            #print(f"url: {url}")
            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }
            
            params = {
                "namespace": "profile-classic-tw",
                "locale": "en_TW"
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                # 緩存結果
                self.character_cache[cache_key] = data
                #print(f"data: {data}")
                return data
            else:
                print(f"⚠ 無法獲取角色 {character_name} 的詳情: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            print(f"⚠ 獲取角色 {character_name} 詳情時發生錯誤: {e}")
            return None

    def enrich_character_data(self, character_data: Dict, realm_slug: str) -> Dict:
        """豐富角色數據，添加職業和種族信息"""
        character_name = character_data.get('name')
        if not character_name:
            return character_data
            
        # 獲取角色詳情
        character_details = self.fetch_character_details(realm_slug, character_name)
        
        if character_details:
            # 添加職業信息
            if 'character_class' in character_details:
                character_data['playable_class'] = character_details['character_class']
            
            # 添加種族信息
            if 'race' in character_details:
                character_data['playable_race'] = character_details['race']
                
            print(f"✓ 已獲取角色 {character_name} 的詳細信息")
        else:
            print(f"⚠ 無法獲取角色 {character_name} 的詳細信息")
            
        return character_data

    def process_entries_with_character_details(self, entries: List[Dict]) -> List[Dict]:
        """處理排行榜條目，添加角色詳細信息"""
        enriched_entries = []
        total_entries = len(entries)
        
        print(f"開始處理 {total_entries} 個排行榜條目...")
        
        for i, entry in enumerate(entries, 1):
            print(f"處理進度: {i}/{total_entries}")
            
            if 'character' in entry:
                # Season 9+ 格式：個人排行榜
                realm_slug = entry['character'].get('realm', {}).get('slug', 'unknown')
                entry['character'] = self.enrich_character_data(entry['character'], realm_slug)
                
            elif 'team' in entry and 'members' in entry['team']:
                # Season 8- 格式：團隊排行榜
                for member in entry['team']['members']:
                    if 'character' in member:
                        realm_slug = member['character'].get('realm', {}).get('slug', 'unknown')
                        member['character'] = self.enrich_character_data(member['character'], realm_slug)
            
            enriched_entries.append(entry)
            
            # 添加小延遲避免API限制
            if i % 10 == 0:
                print("暫停 2 秒避免 API 限制...")
                #time.sleep(0.02)
        
        print(f"✓ 完成處理所有條目")
        return enriched_entries

    def fetch_bracket_data(self, bracket: str, season: int = 12, enrich_data: bool = True) -> Optional[Dict]:
        """獲取指定賽制的排行榜資料"""
        if not self.access_token:
            print("✗ 請先獲取 access token")
            return None
            
        # Season 8- 不支援 rbg
        if season < 9 and bracket == 'rbg':
            print(f"⚠ Season {season} 不支援 {bracket} 賽制")
            return None
            
        if bracket not in self.available_brackets:
            print(f"✗ 不支援的賽制: {bracket}")
            return None
            
        try:
            # 根據賽季選擇正確的 API URL
            url = self.get_api_url(season, bracket)
            
            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }
            
            params = {
                "namespace": "dynamic-classic-tw",
                "locale": "en_TW"
            }
            
            print(f"正在獲取 Season {season} {bracket} 基礎資料...")
            print(f"使用 URL: {url}")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"✗ HTTP 錯誤 {response.status_code}")
                print(f"錯誤內容: {response.text}")
                return None
                
            if not response.text.strip():
                print("✗ API 回傳空的回應")
                return None
            
            data = response.json()
            
            if 'error' in data:
                print(f"✗ {bracket} API 錯誤: {data.get('error', {}).get('message', 'Unknown error')}")
                return None
            
            entry_count = len(data.get('entries', []))
            print(f"✓ {bracket} 成功獲取 {entry_count} 筆基礎資料")
            
            # 如果需要豐富數據且有條目
            if enrich_data and entry_count > 0:
                print(f"開始豐富 {bracket} 的角色資料...")
                data['entries'] = self.process_entries_with_character_details(data['entries'])
                print(f"✓ {bracket} 資料豐富化完成")
            
            return data
                
        except requests.exceptions.Timeout:
            print(f"✗ {bracket} 請求超時")
            return None
        except requests.exceptions.ConnectionError:
            print(f"✗ {bracket} 連線錯誤")
            return None
        except json.JSONDecodeError as e:
            print(f"✗ {bracket} JSON 解析錯誤: {e}")
            return None
        except Exception as e:
            print(f"✗ 獲取 {bracket} 資料時發生錯誤: {e}")
            return None

    def get_available_brackets_for_season(self, season: int) -> List[str]:
        """取得指定賽季可用的賽制"""
        if season < 9:
            # Season 8- 沒有 rbg
            return ['2v2', '3v3', '5v5']
        else:
            # Season 9+ 包含 rbg
            return ['2v2', '3v3', '5v5', 'rbg']

    def save_raw_data(self, data: Dict, bracket: str, season: int, output_dir: str = "./data") -> str:
        """儲存原始 JSON 資料 - 使用新的檔名格式"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # 新的檔名格式：season_6_2v2_tw_arena.json
            filename = f"{output_dir}/season_{season}_{bracket}_tw_arena.json"
            
            with open(filename, "w", encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✓ {bracket} 資料已儲存到: {filename}")
            return filename
            
        except Exception as e:
            print(f"✗ 儲存 {bracket} 資料時發生錯誤: {e}")
            return ""

def get_user_choice(prompt: str, options: List[str]) -> List[str]:
    """獲取使用者選擇"""
    print(f"\n{prompt}")
    print("可選選項:")
    for i, option in enumerate(options, 1):
        print(f"{i}. {option}")
    print(f"{len(options)+1}. 全選")
    
    # 如果包含 rbg，則新增 "rbg以外全選" 選項
    has_rbg = 'rbg' in options
    if has_rbg:
        print(f"{len(options)+2}. rbg以外全選")
    
    print("0. 跳過")
    
    while True:
        try:
            choice = input("請輸入選項 (可用逗號分隔多個選項，例如: 1,3): ").strip()
            
            if choice == '0':
                return []
            elif choice == str(len(options)+1):
                # 全選
                return options.copy()
            elif has_rbg and choice == str(len(options)+2):
                # rbg以外全選
                return [option for option in options if option != 'rbg']
            else:
                indices = [int(x.strip()) for x in choice.split(',')]
                selected = []
                for idx in indices:
                    if 1 <= idx <= len(options):
                        selected.append(options[idx-1])
                    else:
                        print(f"無效選項: {idx}")
                        break
                else:
                    return selected
                    
        except ValueError:
            print("請輸入有效的數字")

def get_season_input() -> List[int]:
    """獲取使用者輸入的賽季 - 支援單季或全部"""
    while True:
        print("\n請選擇要抓取的賽季:")
        print("1. 單個賽季")
        print("2. 全部賽季 (Season 1-11)")
        
        try:
            mode = input("請輸入選項 (1 或 2): ").strip()
            
            if mode == '1':
                # 單個賽季模式
                while True:
                    try:
                        season = input("請輸入要抓取的賽季編號 (例如: 12): ").strip()
                        season_num = int(season)
                        if season_num < 1:
                            print("賽季編號必須大於 0")
                            continue
                        return [season_num]
                    except ValueError:
                        print("請輸入有效的數字")
                        
            elif mode == '2':
                # 全部賽季模式
                print("將抓取 Season 1 到 Season 11 的所有資料")
                confirm = input("確認要處理所有賽季嗎？(y/n): ").strip().lower()
                if confirm == 'y' or confirm == 'yes' or confirm == '':
                    return list(range(5, 12))  # Season 1-11
                else:
                    continue
            else:
                print("請輸入 1 或 2")
                
        except ValueError:
            print("請輸入有效的選項")

def process_single_season(wow_client: WoWPvPLeaderboard, season: int, selected_brackets: List[str], enrich_data: bool) -> int:
    """處理單個賽季的資料"""
    print(f"\n{'='*60}")
    print(f"處理 Season {season}")
    print(f"{'='*60}")
    
    # 根據賽季獲取可用的賽制，並過濾使用者選擇
    available_brackets = wow_client.get_available_brackets_for_season(season)
    season_brackets = [bracket for bracket in selected_brackets if bracket in available_brackets]
    
    if not season_brackets:
        print(f"⚠ Season {season} 沒有可處理的賽制")
        return 0
    
    if season >= 9:
        print(f"✓ Season {season} 使用新版 API (包含戰場排行榜)")
    else:
        print(f"✓ Season {season} 使用舊版 API (不包含戰場排行榜)")
        if 'rbg' in selected_brackets:
            print(f"⚠ Season {season} 不支援 rbg，將跳過")
    
    success_count = 0
    for bracket in season_brackets:
        print(f"\n{'-'*40}")
        print(f"處理 Season {season} {bracket} 資料...")
        print(f"{'-'*40}")
        
        raw_data = wow_client.fetch_bracket_data(bracket, season, enrich_data)
        
        if raw_data:
            filename = wow_client.save_raw_data(raw_data, bracket, season)
            if filename:
                success_count += 1
                
        # 在每個 bracket 之間添加短暫延遲
        if bracket != season_brackets[-1]:  # 不是最後一個
            print("暫停 3 秒避免 API 限制...")
            #time.sleep(0.03)
    
    print(f"\nSeason {season} 處理完成: {success_count}/{len(season_brackets)} 個賽制成功")
    return success_count

def main():
    """主程式"""
    print("=" * 60)
    print("    WoW PvP 排行榜資料抓取工具 (兼容新舊版本)")
    print("=" * 60)
    
    # 初始化 API 客戶端
    wow_client = WoWPvPLeaderboard(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET"
    )
    
    # 獲取 access token
    if not wow_client.get_access_token():
        print("無法繼續，請檢查 API 憑證")
        return
    
    # 獲取要抓取的賽季列表
    seasons = get_season_input()
    
    # 根據最高賽季決定顯示的賽制選項
    max_season = max(seasons)
    all_possible_brackets = wow_client.get_available_brackets_for_season(max_season)
    
    print(f"\n要處理的賽季: {', '.join(map(str, seasons))}")
    if max_season >= 9:
        print("注意: Season 9+ 支援戰場排行榜 (rbg)")
    
    # 使用者選擇要處理的賽制
    selected_brackets = get_user_choice(
        "請選擇要抓取的賽制:", 
        all_possible_brackets
    )
    
    if not selected_brackets:
        print("未選擇任何賽制，程式結束")
        return
    
    print(f"\n已選擇賽制: {', '.join(selected_brackets)}")
    
    # 詢問是否需要豐富化數據
    print("\n是否需要獲取角色詳細信息（職業、種族）(S5之前選N)？")
    print("注意：這會大幅增加處理時間，但能獲得完整的角色信息")
    enrich_choice = input("請輸入 y/n (預設為 n): ").strip().lower()
    enrich_data = enrich_choice == 'y' or enrich_choice == 'yes'
    
    if enrich_data:
        print("✓ 將獲取完整的角色詳細信息")
    else:
        print("⚠ 將只獲取基礎排行榜信息")
    
    # 處理所有賽季
    total_success = 0
    total_possible = 0
    
    start_time = time.time()
    
    for season in seasons:
        season_success = process_single_season(wow_client, season, selected_brackets, enrich_data)
        total_success += season_success
        
        # 計算該賽季可能的賽制數量
        available_brackets = wow_client.get_available_brackets_for_season(season)
        season_brackets = [bracket for bracket in selected_brackets if bracket in available_brackets]
        total_possible += len(season_brackets)
        
        # 在賽季之間添加延遲（除了最後一個賽季）
        if season != seasons[-1]:
            print(f"\n{'='*40}")
            print("賽季間暫停 5 秒避免 API 限制...")
            print(f"{'='*40}")
            #time.sleep(5)
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    # 顯示最終處理結果
    print("\n" + "=" * 80)
    print("最終處理完成摘要:")
    print("=" * 80)
    print(f"處理賽季: {', '.join(map(str, seasons))}")
    print(f"選擇賽制: {', '.join(selected_brackets)}")
    print(f"總成功數: {total_success}/{total_possible} 個檔案")
    print(f"檔案儲存位置: ./data/ 資料夾")
    print(f"檔案命名格式: season_X_bracket_tw_arena.json")
    
    if enrich_data:
        print("✓ 已包含完整的角色職業和種族信息")
    else:
        print("⚠ 僅包含基礎排行榜信息")
    
    print(f"總處理時間: {elapsed_time:.1f} 秒")
    
    if len(seasons) > 1:
        print("✓ 已處理多個賽季")
    
    print("\n感謝使用 WoW PvP 排行榜工具！")

if __name__ == "__main__":
    main()