"""
승강기 정보 및 검사이력 조회 서비스 v4.0
────────────────────────────────────────
데이터ID   : 15151209
제공기관   : 한국승강기안전공단
Base URL   : https://apis.data.go.kr/B553664/ElevatorInformationService

승인된 오퍼레이션
  - getElevatorViewM   : 건물 기준 승강기 목록 / 고유번호 기준 상세정보 조회
  - getElevatorInspHisM: 승강기 검사이력 조회
"""

import tkinter as tk
from tkinter import ttk, messagebox
import urllib.parse
import xml.etree.ElementTree as ET
import csv
import os
from datetime import datetime
import threading
import requests
requests.packages.urllib3.disable_warnings()

# ─────────────────────────────────────────────────────────
# API 엔드포인트 (15151209 기준)
# ─────────────────────────────────────────────────────────
BASE = "https://apis.data.go.kr/B553664/ElevatorInformationService"

MODES = {
    "🏢 승강기 목록 조회 (건물명/주소 기준)": {
        "url":    BASE + "/getElevatorListM",
        "params": "list",
        "hint":   "시도·시군구·건물명 중 하나 이상 입력",
    },
    "🔍 승강기 상세정보 (고유번호 기준)": {
        "url":    BASE + "/getElevatorListM",
        "params": "no",
        "hint":   "승강기 고유번호 필수 (목록 결과 더블클릭 → 자동입력)",
    },
    "📋 승강기 검사이력 (고유번호 기준)": {
        "url":    BASE + "/getElevatorInspHisM",
        "params": "no",
        "hint":   "승강기 고유번호 필수",
    },
}

SIDO_LIST = [
    "", "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "충청북도", "충청남도",
    "전북특별자치도", "전남광주통합특별시", "경상북도", "경상남도", "제주특별자치도",
]

# 출력 컬럼 → 한글 레이블
COL_LABEL = {
    # getElevatorListM 출력 (camelCase)
    "address1":           "주소",
    "address2":           "상세주소",
    "buldNm":             "건물명",
    "divGroundFloorCnt":  "지상층수",
    "elvtrStts":          "상태",
    "liveLoad":           "적재하중(kg)",
    "ratedCap":           "최대정원",
    # 추가 참고 컬럼
    "elvtrNo":            "승강기번호",
    "elvtrDivNm":         "승강기구분",
    "elvtrKndNm":         "승강기종류",
    "sigunguNm":          "시군구",
    "sidoNm":             "시도",
    "lastInspDe":         "최종검사일",
    "lastInspRsltNm":     "검사판정",
    "inspValidDe":        "검사유효기간",
    # 설치위치 관련
    "installationPlace":  "설치위치",
    "instlPlc":           "설치위치",
    "instl_plc":          "설치위치",
    "installPlace":       "설치위치",
    "install_place":      "설치위치",
    "instlLoc":           "설치위치",
    "instl_loc":          "설치위치",
    # 동(棟) 관련
    "dongNm":             "동명",
    "dong_nm":            "동명",
    "buldDongNm":         "동명",
    "buld_dong_nm":       "동명",
    "hoNm":               "호기",
    "ho_no":              "호기",
    # snake_case 대비
    "elvtr_no":           "승강기번호",
    "elvtr_sttus_nm":     "상태",
    "elvtr_div_nm":       "승강기구분",
    "bild_nm":            "건물명",
    "adres":              "주소",
    "load_wght":          "적재하중(kg)",
    "ride_num":           "최대정원",
    "grnd_floor_cnt":     "지상층수",
    # getElevatorInspHisM 출력
    "insp_de":            "검사일",
    "insp_knd_nm":        "검사종류",
    "insp_rslt_nm":       "판정결과",
    "insp_orgn_nm":       "검사기관",
    "insp_chrgr_nm":      "검사담당자",
}

# 목록/상세 조회 표시 컬럼 (이 컬럼만 출력, 순서 고정)
DISPLAY_COLS = [
    "address1", "address2", "buldNm",
    "installationPlace", "divGroundFloorCnt",
    "liveLoad", "ratedCap", "elvtrStts",
]

# 검사이력 조회 표시 컬럼
INSP_COLS = [
    "insp_de", "insp_knd_nm", "insp_rslt_nm", "insp_orgn_nm", "insp_chrgr_nm",
    "inspDe", "inspKndNm", "inspRsltNm", "inspOrgnNm", "inspChrgrNm",
]

ERR_CODE = {
    "10": "잘못된 요청 파라미터",
    "12": "필수 파라미터 누락",
    "20": "서비스 접근 거부",
    "22": "일일 요청 한도 초과",
    "30": "미등록 서비스키\n→ data.go.kr에서 데이터ID [15151209] 활용신청 후 승인 확인",
    "31": "활용 기간 만료",
    "32": "잘못된 서비스키",
    "99": "기타 오류",
}

LAST_ROWS: list = []
LAST_COLS: list = []
SORT_STATE: dict = {}  # {col: "asc" | "desc"}


# ─────────────────────────────────────────────────────────
# XML 파싱
# ─────────────────────────────────────────────────────────
def parse_xml(raw: bytes):
    try:
        root_el = ET.fromstring(raw)
    except ET.ParseError as e:
        preview = raw[:400].decode("utf-8", errors="replace")
        raise ValueError(f"XML 파싱 실패: {e}\n\n응답 미리보기:\n{preview}")

    # 에러코드 체크
    code = (root_el.findtext(".//returnReasonCode") or
            root_el.findtext(".//resultCode") or "")
    code = code.strip()
    if code and code not in ("00", "0000"):
        msg = ERR_CODE.get(code[:2], f"알 수 없는 오류 (코드: {code})")
        raise ValueError(f"API 오류:\n{msg}")

    total = (root_el.findtext(".//totalCount") or
             root_el.findtext(".//total_count") or "0").strip()

    items = []
    for item in root_el.iter("item"):
        row = {c.tag.strip(): (c.text or "").strip() for c in item}
        if row:
            items.append(row)
    return items, total


# ─────────────────────────────────────────────────────────
# API 호출
# ─────────────────────────────────────────────────────────
def call_api(url: str, params: dict):
    svc_key = API_KEY_VAR.get().strip()
    if not svc_key:
        raise ValueError("서비스키를 입력하세요.")

    params["pageNo"]    = PAGE_NO_VAR.get().strip() or "1"
    params["numOfRows"] = NUM_ROWS_VAR.get().strip() or "100"

    # 서비스키 이중인코딩 방지: 직접 조합
    encoded_key  = urllib.parse.quote(svc_key, safe="")
    other_params = urllib.parse.urlencode(params)
    full_url     = url + "?serviceKey=" + encoded_key + "&" + other_params

    try:
        resp = requests.get(
            full_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=60,
            verify=False,
        )
        raw = resp.content
    except requests.exceptions.ConnectionError as e:
        raise ValueError(f"네트워크 오류: 서버에 연결할 수 없습니다.\n{e}")
    except requests.exceptions.Timeout:
        raise ValueError("네트워크 오류: 응답 시간이 초과되었습니다.\n잠시 후 다시 시도하세요.")
    except Exception as e:
        raise ValueError(f"네트워크 오류: {e}")

    return parse_xml(raw)


# ─────────────────────────────────────────────────────────
# 검색 실행
# ─────────────────────────────────────────────────────────
def do_search():
    mode_key  = MODE_VAR.get()
    mode_info = MODES.get(mode_key)
    if not mode_info:
        return

    btn_search.config(state="disabled", text="⏳ 조회 중...")
    status_var.set("  ⏳ API 호출 중... 잠시 기다려 주세요.")

    def run():
        try:
            url   = mode_info["url"]
            ptype = mode_info["params"]
            params = {}

            if ptype == "list":
                sido     = SIDO_VAR.get().strip()
                sigungu  = SIGUNGU_VAR.get().strip()
                building = BUILDING_VAR.get().strip()
                # sido 필수
                if not sido:
                    root_win.after(0, lambda: messagebox.showwarning(
                        "조건 입력", "시도는 필수 입력값입니다.\n시도를 선택해 주세요."))
                    return
                params["sido"] = sido
                if sigungu:  params["sigungu"]  = sigungu
                if building: params["buld_nm"]  = building

            else:  # ptype == "no"
                elev_no = ELEV_NO_VAR.get().strip()
                if not elev_no:
                    root_win.after(0, lambda: messagebox.showwarning(
                        "입력 오류",
                        "승강기 고유번호를 입력하세요.\n\n"
                        "💡 먼저 [승강기 목록 조회]로 검색 후\n"
                        "   결과 행을 더블클릭하면 자동 입력됩니다."))
                    return
                params["elvtNo"] = elev_no

            rows, total = call_api(url, params)
            root_win.after(0, lambda: show_results(rows, mode_key, total))

        except ValueError as e:
            err = str(e)
            root_win.after(0, lambda: (
                messagebox.showerror("오류", err),
                status_var.set(f"  ❌ {err.splitlines()[0][:80]}")
            ))
        except Exception as e:
            root_win.after(0, lambda: (
                messagebox.showerror("예기치 못한 오류", str(e)),
                status_var.set("  ❌ 오류 발생")
            ))
        finally:
            root_win.after(0, lambda: btn_search.config(
                state="normal", text="🔍  검색"))

    threading.Thread(target=run, daemon=True).start()


# ─────────────────────────────────────────────────────────
# 결과 표시
# ─────────────────────────────────────────────────────────
def show_results(rows: list, mode: str, total: str):
    for item in tree.get_children():
        tree.delete(item)

    if not rows:
        status_var.set(f"  ⚠️  결과 없음 — API 총 건수: {total}건  (조건을 변경해 보세요)")
        tree["columns"] = []
        return

    all_cols = list(rows[0].keys())

    # 조회 유형에 따라 표시 컬럼 선택
    if "insp" in mode.lower() or "검사" in mode:
        target = INSP_COLS
    else:
        target = DISPLAY_COLS

    # 지정 컬럼 중 실제 응답에 있는 것만 필터
    cols = [c for c in target if c in all_cols]

    # 지정 컬럼이 하나도 없으면 전체 출력 (fallback)
    if not cols:
        cols = all_cols

    tree["columns"] = cols
    tree["show"]    = "headings"

    # 컬럼 너비 최적화
    COL_WIDTH = {
        "address1": 200, "address2": 120, "buldNm": 150,
        "dongNm": 80, "dong_nm": 80, "buldDongNm": 80, "buld_dong_nm": 80,
        "installationPlace": 160, "instlPlc": 160, "instl_plc": 160,
        "installPlace": 160, "install_place": 160, "instlLoc": 160, "instl_loc": 160,
        "divGroundFloorCnt": 80, "elvtrStts": 80,
        "liveLoad": 100, "ratedCap": 80,
        "adres": 200, "bild_nm": 150, "grnd_floor_cnt": 80,
        "elvtr_sttus_nm": 80, "load_wght": 100, "ride_num": 80,
        "insp_de": 100, "insp_knd_nm": 100, "insp_rslt_nm": 80,
        "insp_orgn_nm": 150, "insp_chrgr_nm": 100,
    }
    SORT_STATE.clear()
    for col in cols:
        label = COL_LABEL.get(col, col)
        w = COL_WIDTH.get(col, max(90, len(label) * 14))
        tree.heading(col, text=label, anchor="center",
                     command=lambda c=col: sort_by_col(c))
        tree.column(col, width=w, anchor="center", minwidth=60, stretch=True)

    # 교대 행 색상
    tree.tag_configure("odd",  background="#ffffff")
    tree.tag_configure("even", background="#f0f7ff")

    for i, row in enumerate(rows):
        tag = "even" if i % 2 == 0 else "odd"
        tree.insert("", "end", values=[row.get(c, "") for c in cols], tags=(tag,))

    now = datetime.now().strftime("%H:%M:%S")
    status_var.set(
        f"  ✅  {mode}  |  {len(rows)}건 표시 / 총 {total}건   [{now}]"
    )
    LAST_ROWS.clear(); LAST_ROWS.extend(rows)
    LAST_COLS.clear(); LAST_COLS.extend(cols)


def sort_by_col(col):
    """컬럼 헤더 클릭 → 오름차순/내림차순 정렬 (installationPlace 포함)"""
    rows_data = [(tree.set(k, col), k) for k in tree.get_children("")]
    if not rows_data:
        return

    asc = SORT_STATE.get(col, None) != "asc"
    SORT_STATE[col] = "asc" if asc else "desc"

    # 숫자형 정렬 시도
    try:
        rows_data.sort(key=lambda x: float(x[0]) if x[0] else 0, reverse=not asc)
    except ValueError:
        rows_data.sort(key=lambda x: x[0], reverse=not asc)

    for idx, (_, k) in enumerate(rows_data):
        tree.move(k, "", idx)

    # 교대 행 색상 재적용
    tree.tag_configure("odd",  background="#ffffff")
    tree.tag_configure("even", background="#f0f7ff")
    for idx, item in enumerate(tree.get_children("")):
        tree.item(item, tags=("even" if idx % 2 == 0 else "odd",))

    # 헤더 정렬 표시 업데이트
    for c in tree["columns"]:
        label = COL_LABEL.get(c, c)
        if c == col:
            arrow = " ▲" if asc else " ▼"
            tree.heading(c, text=label + arrow)
        else:
            tree.heading(c, text=label)

    status_var.set(
        f"  🔃  [{COL_LABEL.get(col, col)}] {'오름차순' if asc else '내림차순'} 정렬 완료"
    )


def on_double_click(event):
    """행 더블클릭 → 승강기 고유번호 자동 입력"""
    sel = tree.selection()
    if not sel:
        return
    vals = tree.item(sel[0], "values")
    cols = list(tree["columns"])
    # 고유번호 컬럼 탐색
    for key in ("elvtr_no", "elvtNo", "elev_no"):
        if key in cols:
            ELEV_NO_VAR.set(vals[cols.index(key)])
            status_var.set(f"  ℹ️  승강기 고유번호 [{vals[cols.index(key)]}] 자동 입력 완료")
            return


# ─────────────────────────────────────────────────────────
# CSV 저장
# ─────────────────────────────────────────────────────────
def save_csv():
    if not LAST_ROWS:
        messagebox.showinfo("알림", "저장할 데이터가 없습니다.")
        return
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"elevator_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LAST_COLS)
        w.writeheader()
        w.writerows(LAST_ROWS)
    messagebox.showinfo("저장 완료", f"저장 위치:\n{path}")


# ─────────────────────────────────────────────────────────
# 패널 전환
# ─────────────────────────────────────────────────────────
def on_mode_change(*_):
    info = MODES.get(MODE_VAR.get())
    if not info:
        return
    frame_list.grid_remove()
    frame_detail.grid_remove()
    hint_var.set(f"  💡 {info['hint']}")
    if info["params"] == "list":
        frame_list.grid()
    else:
        frame_detail.grid()


# ─────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────
root_win = tk.Tk()
root_win.title("🛗 승강기 정보 검색 시스템 v4.0  (데이터ID: 15151209)")
root_win.geometry("1180x750")
root_win.resizable(True, True)
root_win.configure(bg="#f0f4f8")

style = ttk.Style()
style.theme_use("clam")
style.configure("Treeview",
                font=("맑은 고딕", 10), rowheight=26,
                borderwidth=0, relief="flat")
style.configure("Treeview.Heading",
                font=("맑은 고딕", 10, "bold"),
                background="#1e3a5f", foreground="#ffffff",
                relief="flat", padding=(8, 6))
style.map("Treeview",
          background=[("selected", "#1e88e5")],
          foreground=[("selected", "#ffffff")])

# ── 헤더 ────────────────────────────────────
hdr = tk.Frame(root_win, bg="#1e3a5f")
hdr.pack(fill="x")
tk.Label(hdr, text="🛗  승강기 정보 검색 시스템",
         bg="#1e3a5f", fg="white",
         font=("맑은 고딕", 14, "bold")).pack(side="left", padx=18, pady=10)
tk.Label(hdr, text="데이터ID: 15151209  |  openapi.elevator.go.kr",
         bg="#1e3a5f", fg="#90caf9",
         font=("맑은 고딕", 9)).pack(side="right", padx=18)

# ── 본문 ────────────────────────────────────
main = tk.Frame(root_win, bg="#f0f4f8")
main.pack(fill="both", expand=True, padx=14, pady=8)

# ── 카드 1 : 서비스키 + 조회유형 ─────────────
c1 = tk.Frame(main, bg="#ffffff", bd=1, relief="solid")
c1.pack(fill="x", pady=(0, 6))
r1 = tk.Frame(c1, bg="#ffffff", padx=12, pady=10)
r1.pack(fill="x")

tk.Label(r1, text="서비스키:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=0, sticky="w", padx=(0, 4))
API_KEY_VAR = tk.StringVar(value="Nk1gZqwq9vj6Fbc2xYbFLsQ7T/zoxaUuPKKsz4yA2luxXuxdgo+kNnkxewpcNgKJUlWobyD4gcp4gySymzj4aA==")
api_ent = tk.Entry(r1, textvariable=API_KEY_VAR, width=52,
                   show="*", font=("맑은 고딕", 10))
api_ent.grid(row=0, column=1, padx=(0, 4))

show_sv = tk.BooleanVar()
def _toggle(): api_ent.config(show="" if show_sv.get() else "*")
tk.Checkbutton(r1, text="표시", variable=show_sv, command=_toggle,
               bg="#ffffff", font=("맑은 고딕", 9)).grid(row=0, column=2, padx=(0, 16))

tk.Label(r1, text="조회 유형:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=3, sticky="w", padx=(0, 4))
MODE_VAR = tk.StringVar(value=list(MODES.keys())[0])
ttk.Combobox(r1, textvariable=MODE_VAR, values=list(MODES.keys()),
             state="readonly", width=34).grid(row=0, column=4, sticky="w")
MODE_VAR.trace_add("write", on_mode_change)

# 안내문
tk.Label(r1,
         text="※ data.go.kr → 데이터ID [15151209] 검색 → 활용신청 → 마이페이지 → 인증키(Decoding) 복사",
         bg="#ffffff", fg="#c62828",
         font=("맑은 고딕", 8)).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))

# ── 카드 2 : 검색 조건 ───────────────────────
c2 = tk.Frame(main, bg="#ffffff", bd=1, relief="solid")
c2.pack(fill="x", pady=(0, 6))
r2 = tk.Frame(c2, bg="#ffffff", padx=12, pady=10)
r2.pack(fill="x")

# 패널 A : 목록 (건물 기준)
frame_list = tk.Frame(r2, bg="#ffffff")
frame_list.grid(row=0, column=0, sticky="w")

SIDO_VAR     = tk.StringVar(value="전남광주통합특별시")
SIGUNGU_VAR  = tk.StringVar(value="여수시")
BUILDING_VAR = tk.StringVar()

tk.Label(frame_list, text="시도:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=0, sticky="w", padx=(0, 4))
ttk.Combobox(frame_list, textvariable=SIDO_VAR, values=SIDO_LIST,
             state="readonly", width=14).grid(row=0, column=1, padx=(0, 12))

tk.Label(frame_list, text="시군구:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=2, sticky="w", padx=(0, 4))
tk.Entry(frame_list, textvariable=SIGUNGU_VAR, width=10,
         font=("맑은 고딕", 10)).grid(row=0, column=3, padx=(0, 12))

tk.Label(frame_list, text="건물명:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=4, sticky="w", padx=(0, 4))
tk.Entry(frame_list, textvariable=BUILDING_VAR, width=20,
         font=("맑은 고딕", 10)).grid(row=0, column=5)

# 패널 B : 고유번호 기준
frame_detail = tk.Frame(r2, bg="#ffffff")
frame_detail.grid(row=0, column=0, sticky="w")
frame_detail.grid_remove()

ELEV_NO_VAR = tk.StringVar()
tk.Label(frame_detail, text="승강기 고유번호:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=0, sticky="w", padx=(0, 4))
tk.Entry(frame_detail, textvariable=ELEV_NO_VAR, width=22,
         font=("맑은 고딕", 10)).grid(row=0, column=1, padx=(0, 10))
tk.Label(frame_detail, text="(목록 결과에서 행 더블클릭 → 자동입력)",
         bg="#ffffff", fg="#9e9e9e",
         font=("맑은 고딕", 8)).grid(row=0, column=2)

# 페이지번호 / 결과수 입력란
PAGE_NO_VAR  = tk.StringVar(value="1")
NUM_ROWS_VAR = tk.StringVar(value="100")

page_frame = tk.Frame(r2, bg="#ffffff")
page_frame.grid(row=1, column=0, sticky="w", pady=(6, 0))

tk.Label(page_frame, text="페이지번호:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=0, sticky="w", padx=(0, 4))
tk.Entry(page_frame, textvariable=PAGE_NO_VAR, width=5,
         font=("맑은 고딕", 10)).grid(row=0, column=1, padx=(0, 16))

tk.Label(page_frame, text="결과수:", bg="#ffffff",
         font=("맑은 고딕", 10)).grid(row=0, column=2, sticky="w", padx=(0, 4))
ttk.Combobox(page_frame, textvariable=NUM_ROWS_VAR,
             values=["10", "50", "100", "200", "500"],
             state="readonly", width=6).grid(row=0, column=3, padx=(0, 16))

# 힌트 레이블
hint_var = tk.StringVar(value="  💡 " + list(MODES.values())[0]["hint"])
tk.Label(r2, textvariable=hint_var, bg="#ffffff", fg="#1565c0",
         font=("맑은 고딕", 8)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

# 버튼
r2.columnconfigure(1, weight=1)
bf = tk.Frame(r2, bg="#ffffff")
bf.grid(row=0, column=1, sticky="e")

btn_search = tk.Button(bf, text="🔍  검색", command=do_search,
                       bg="#1e88e5", fg="white",
                       font=("맑은 고딕", 11, "bold"),
                       relief="flat", padx=18, pady=5, cursor="hand2")
btn_search.pack(side="left", padx=(0, 8))

tk.Button(bf, text="💾 CSV 저장", command=save_csv,
          bg="#43a047", fg="white",
          font=("맑은 고딕", 10, "bold"),
          relief="flat", padx=12, pady=5, cursor="hand2").pack(side="left")

# ── 결과 테이블 ──────────────────────────────
rf = tk.Frame(main, bg="#ffffff", bd=1, relief="solid")
rf.pack(fill="both", expand=True)

sy = ttk.Scrollbar(rf, orient="vertical")
sx = ttk.Scrollbar(rf, orient="horizontal")
tree = ttk.Treeview(rf, yscrollcommand=sy.set, xscrollcommand=sx.set)
sy.config(command=tree.yview)
sx.config(command=tree.xview)
sy.pack(side="right",  fill="y")
sx.pack(side="bottom", fill="x")
tree.pack(fill="both", expand=True)
tree.bind("<Double-1>", on_double_click)

# ── 상태바 ───────────────────────────────────
status_var = tk.StringVar(
    value="  서비스키를 입력하고 검색하세요.  |  목록 행 더블클릭 → 고유번호 자동입력")
tk.Label(root_win, textvariable=status_var,
         bd=1, relief="sunken", anchor="w",
         bg="#e3f2fd", fg="#1565c0",
         font=("맑은 고딕", 9), padx=8).pack(fill="x", side="bottom")

on_mode_change()
root_win.mainloop()
