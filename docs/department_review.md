# 학과 소스 1차 검토 보고서 (2026-10-03)

Claude가 `scripts/review_drafts.py` 기준으로 1차 검토한 결과. 사람 2차 검토 때 **확인 필요** 항목부터 본다.
수정은 `config/review_overrides.yaml`에 적고 `python -m scripts.review_drafts`로 다시 생성한다.

- 공개 98개 · 보류 0개

## 확인 필요
- **animal** 동물생명공학전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/animal/-10 (내용: 준 비 중 입 니 다)
- **archi** 건축학전공·건축공학전공
  - same_as 추정: 외부행사 및 공모전 = 건축학전공 외부특강 및 공모전 (182건)
  - dept_info 경로에 포틀릿 파라미터가 섞임: /web/archi/-5-p_p_id-deptinfo_war_empinfoportlet-p_p_lifecyc… (동작은 함, 정리 권장)
  - dept_info 경로에 포틀릿 파라미터가 섞임: /web/archi/-1-p_p_id-deptinfo_war_empinfoportlet-p_p_lifecyc… (동작은 함, 정리 권장)
  - professors 경로에 포틀릿 파라미터가 섞임: /web/archi/-5-p_p_id-deptinfo_war_empinfoportlet-p_p_lifecyc… (동작은 함, 정리 권장)
- **biomedical** 임상병리학과
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **communicationdesign** 커뮤니케이션디자인전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/communicationdesign/공지사항 (내용: 비어 있음)
- **composition** 작곡전공
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **counseling** 상담학과
  - dept_info 경로에 포틀릿 파라미터가 섞임: /web/counseling/introduce_b-p_p_id-deptinfo_war_empinfoportl… (동작은 함, 정리 권장)
  - professors 경로에 포틀릿 파라미터가 섞임: /web/counseling/introduce_b-p_p_id-deptinfo_war_empinfoportl… (동작은 함, 정리 권장)
- **danche** 체육교육과
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/danche/공지사항 (내용: 비어 있음)
  - → 공지 링크가 게시판이 아님: /web/danche/-10 (내용: 비어 있음)
  - → 공지 링크가 게시판이 아님: /web/danche/-4 (내용: 준 비 중 입 니 다)
- **dkcw** 문예창작과
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/dkcw/학부-공지사항 — 등록 불가
- **dsm** 스포츠경영학과
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/dsm/학부-공지사항 — 등록 불가
- **econ** 경제학과
  - dept_info 경로에 포틀릿 파라미터가 섞임: /web/econ/-15-p_p_id-deptinfo_war_empinfoportlet-p_p_lifecyc… (동작은 함, 정리 권장)
- **ere** 식품자원경제학과
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/ere/-17 (내용: 비어 있음)
- **fashion** 패션산업디자인전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/fashion/-6 (내용: 준 비 중 입 니 다)
- **fineart** 서양화전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/fineart/학부-공지사항 (내용: 준 비 중 입 니 다)
- **foodnutrition** 식품영양학과
  - 역할 불명 게시판 제외: 자격증 정보 (/web/foodnutrition/-26, 15건) — 필요하면 overrides roles에 역할 지정
  - 최신 글 (자격증 정보): 2015년 위생사, 영양사시험대비 합격특강반 7월개강 (2015.03.18) / 프라임MD 2016 약대/의·치전원/의대편입 설명회 (2014.06.16) / 항공료 포함 193만원 일본 어학연수 출발하기! (2011.11.08) / 총 296만원 일본 워킹 정착서비스 (2011.11.08) / [안드로이드교육]이공계전문기술연수-무료교육생 모집 (2011.05.27)
- **german** 독일학전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/german/-10 (내용: 준 비 중 입 니 다)
- **healthadmin** 보건행정학과
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/healthadmin/-1 — 등록 불가
- **history** 사학과
  - professors 경로에 포틀릿 파라미터가 섞임: /web/history/-7-p_p_id-deptinfo_war_empinfoportlet-p_p_lifec… (동작은 함, 정리 권장)
- **int_sports** 국제스포츠전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/int_sports/학부-공지사항 — 등록 불가
- **jazzperformance** 재즈퍼포먼스전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/jazzperformance/학부-공지사항 — 등록 불가
- **joso** 조소전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/joso/-10 — 등록 불가
- **koreamusic** 국악전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/koreamusic/학부-공지사항 — 등록 불가
- **landscape** 녹지조경학전공
  - 역할 불명 게시판 제외: FCLA (/web/landscape/fc-, 3건) — 필요하면 overrides roles에 역할 지정
  - 역할 불명 게시판 제외: 그린톡 (/web/landscape/-24, 4건) — 필요하면 overrides roles에 역할 지정
- **newmusicdku** 뮤직테크놀러지전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/newmusicdku/-5 (내용: 준 비 중 입 니 다)
- **orchestral-instrument** 관현악전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/orchestral-instrument/학부-공지사항 — 등록 불가
- **oriental** 동양화전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/oriental/-15 (내용: 준 비 중 입 니 다)
- **performance-film** 연극전공·영화전공·뮤지컬전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/performance-film/공지사항 (내용: 비어 있음)
- **pharm** 제약공학과
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **physical_therapy** 물리치료학과
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **piano** 피아노전공
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **polisci** 정치외교학과
  - 학과 공지(notice) 게시판 없음
  - → 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)
- **psychology** 심리학과·심리치료학과
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/psychology/-11 — 등록 불가
- **singersongwriting** 싱어송라이팅전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/singersongwriting/학부-공지사항 — 등록 불가
- **spain** 스페인중남미학전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/spain/게시판 (내용: 준 비 중 입 니 다)
  - → 공지 링크가 게시판이 아님: /web/spain/학부-공지사항 (내용: 준 비 중 입 니 다)
- **specialedu** 특수교육과
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/specialedu/공지사항 (내용: 비어 있음)
  - → 공지 링크가 게시판이 아님: /web/specialedu/학과-공지사항 (내용: 비어 있음)
  - → 공지 링크가 게시판이 아님: /web/specialedu/학생회-공지사항 (내용: 비어 있음)
- **sports** 생활체육학과
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/sports/-10 (내용: 준 비 중 입 니 다)
- **sportsscience** 운동처방재활전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/sportsscience/-10 — 등록 불가
- **taekwondo** 태권도전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판 비공개(로그인 필요, 접근 거부): /web/taekwondo/학부-공지사항 — 등록 불가
- **teachertraining** 교직교육과
  - 학과 공지(notice) 게시판 없음
  - → 공지 게시판은 초안에 있었지만 1차 검토에서 뺌 (글 수 부족 등): /web/teachertraining/-q-a
- **vocalmusic** 성악전공
  - 학과 공지(notice) 게시판 없음
  - → 공지 링크가 게시판이 아님: /web/vocalmusic/-10 (내용: 준 비 중 입 니 다)

## 학과별 상세
### acc 회계학전공 (죽전, 공개)
- 게시판: rules: 졸업요건 (13건), notice: 학사 공지사항 (395건), scholarship: 장학정보 (56건), jobs: 취업정보 (139건), notice_2: 단현재 공지 (35건), jobs_2: 회계사/세무사 (11건), notice_3: 기타 공지사항 (33건)
- 뺀 게시판: 갤러리 (커뮤니티·사진), 학생회 소개 (커뮤니티·사진), 학생회 공지 (커뮤니티·사진), 학생회 행사 (커뮤니티·사진), 갤러리 (커뮤니티·사진), 인터뷰영상 (글 1건)
- 데이터: dept_info, curriculum, professors
- 페이지: 없음
- 뺀 페이지: Home, 단현재 소개

### ace 컴퓨터공학과 (죽전, 공개)
- 게시판: activity: 공모전정보 (96건), jobs: 일반취업정보 (486건), notice: 공지사항 (1,135건), activity_2: 학과소식 (575건), activity_3: 교육세미나 (39건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 시설, 연혁, 학과장 인사말

### ai 인공지능학과 (죽전, 공개)
- 게시판: notice: 공지사항 (97건), jobs: 채용공지 (69건)
- 뺀 게시판: 학과소식 (글 0건)
- 데이터: professors
- 페이지: location: 오시는 길
- 뺀 페이지: 학과장 인사말, 학과 소개

### archi 건축학전공·건축공학전공 (죽전, 공개)
- 게시판: notice: 건축학전공 학사 (511건), scholarship: 건축학전공 장학 (79건), jobs: 건축학전공 취창업 (729건), activity: 건축학전공 외부특강 및 공모전 (182건), archive: 건축학교육인증 (3건), grad: 건축학과 대학원 공지 (448건), notice_2: 건축공학전공 학사 (992건), grad_2: 건축공학과 대학원 공지 (792건), notice_3: 교직 공지사항 (32건), activity_2: 외부행사 및 공모전 (182건), scholarship_2: 건축공학전공 장학 (119건), archive_2: 공학인증 (6건), jobs_2: 건축공학전공 취창업 (1,074건)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 학부 찾아오시는 길
- 뺀 페이지: 학부장 인사말, 학부 교육시설, 국제교류, 대학원 건축도시기술연구소, 대학원 리모델링연구소

### bahumanities 영미인문학과 (죽전, 공개)
- 게시판: notice: 학과공지사항 (881건), grad: 대학원 공지사항 (118건), jobs: 취업 · 진로 (480건), archive: 자료실 (7건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: professors, dept_info, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말

### bu 경영학전공 (죽전, 공개)
- 게시판: notice: 학사 공지사항(학부) (260건), jobs: 취창업 정보마당 (326건), scholarship: 장학 공지사항 (44건), notice_2: 기타 공지사항 (150건), activity: 학과동정 (14건)
- 뺀 게시판: 대학원내규(일반) (글 1건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 주임교수 인사말

### ceramicarts 도예과 (죽전, 공개)
- 게시판: notice: 학사공지 (4건), activity: 전시일정 (39건), notice_2: 공지사항 (38건), archive: 자료실 (14건), activity_2: 공모전 (9건)
- 뺀 게시판: 갤러리 (커뮤니티·사진), 수상실적 (글 2건)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 찾아오시는 길

### comm 저널리즘전공·영상콘텐츠전공·광고홍보전공 (죽전, 공개)
- 게시판: notice: 학사공지 (11건), archive: 자료실 (5건)
- 뺀 게시판: 공모전 (글 2건), 질문게시판 (커뮤니티·사진), 자유게시판 (커뮤니티·사진)
- 데이터: professors, dept_info, curriculum
- 페이지: location: 찾아오시는길, scholarship: 학부 장학제도, graduation: 졸업요건, grad_bs_ms: 대학원연계과정
- 뺀 페이지: 학부장 인사말, 학부 책임교수제, 학부 학술제 광장, 학생회, 학회(과동아리), 학부 COMM.together, 학부 COMM.panionship, 학부 COMM.memory

### communicationdesign 커뮤니케이션디자인전공 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장인사말, 연혁

### composition 작곡전공 (죽전, 공개)
- 게시판: 없음
- 데이터: professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말

### counseling 상담학과 (죽전, 공개)
- 게시판: notice: 공지사항 (214건), activity: 학과 소식 (17건)
- 뺀 게시판: 학생회 소식 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 연혁, 학술지 소개, 투고 안내

### dance 무용과 (죽전, 공개)
- 게시판: notice: 공지사항 (19건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진), 자료실 (글 2건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 연혁

### danche 체육교육과 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 연혁

### dkucee 인프라건설공학과·토목환경공학과 (죽전, 공개)
- 게시판: notice: 공지사항 (1,161건), jobs: 일자리플러스 (11건), jobs_2: 취업·공모전·참여 (1,024건), activity: 학과소식 (60건)
- 뺀 게시판: 설명 자료 (글 2건), 공모전 출품작 (글 2건), 학생회 소식 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말, 학과연혁, 학과사무실, Q&A, 대학원 입학, 구조공학, 대학원 오픈랩, 학부연구생, 지반공학, 수공학, 환경공학, 스마트인프라, 공모전 지원, 동문회 소개, 동문회 활동

### dkupa 행정학과 (죽전, 공개)
- 게시판: notice: 공지사항 (243건), jobs: 고시반 (7건)
- 뺀 게시판: Q&A (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말, 연혁, 교과과정(교양), 연계전공

### dkustat 통계데이터사이언스학과 (죽전, 공개)
- 게시판: notice: 학과공지 (135건), jobs: 채용정보/취업정보 (161건)
- 뺀 게시판: 공모전/교육 (글 2건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학사일정

### econ 경제학과 (죽전, 공개)
- 게시판: notice: 공지사항 (525건), scholarship: 장학 정보 (84건), jobs: 취업 정보 (483건), activity: 튜터링 (8건), grad: 대학원 공지 (114건), activity_2: 행사 일정 (3건)
- 뺀 게시판: 학생회 소개 (커뮤니티·사진), 학생회 공지 (커뮤니티·사진), 행사 사진 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말, 학과 연혁, 동문회 조직, 장학회

### eee 전자전기공학과 (죽전, 공개)
- 게시판: notice: 학과공지 (564건), grad: 대학원 공지 (768건), jobs: 취업정보 (830건)
- 데이터: professors, dept_info, curriculum
- 페이지: scholarship: 장학제도, location: 찾아오시는 길, grad_labs: 대학원 연구실 소개
- 뺀 페이지: 인사말, 대학원 소개, 대학원 연구분야, 대학원 교육과정, 대학원 학사일정, 대학원 인력양성 사업

### fashion 패션산업디자인전공 (죽전, 공개)
- 게시판: 없음
- 뺀 게시판: 갤러리 (커뮤니티·사진), FMD Q&A (커뮤니티·사진)
- 데이터: dept_info, curriculum, professors
- 페이지: 없음

### fiber 융합소재공학전공·파이버융합소재공학전공 (죽전, 공개)
- 게시판: notice: 학부 공지사항 (157건), grad: 대학원 공지사항 (107건), jobs: 채용정보/행사/특강 (691건), archive: 자료실 (13건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: (구)공학인증(2025년 2월 이전)

### hankyo 한문교육과 (죽전, 공개)
- 게시판: notice: 학과공지사항 (6건), archive: 원전자료 (14건), archive_2: 임용자료 (14건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 진로/취업 (글 0건), 사진첩 (커뮤니티·사진), 취업자료 (글 0건), 봉사활동/멘토링 (글 0건)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 오시는길
- 뺀 페이지: 학과장 인사말, 연혁, 대학원 한문학과, 발전계획, 학생회장 인사말, Home, 서예부, 기획부, 문화복지부, 총무부

### history 사학과 (죽전, 공개)
- 게시판: notice: 공지사항 (243건), activity: 학과소식 (11건), archive: 자료실 (6건), grad: 대학원 공지사항 (9건), grad_2: 대학원 자료실 (5건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 답사사진 (커뮤니티·사진), 행사사진 (커뮤니티·사진), 대학원 사진 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 연혁, 학생회 소개, 학회 소개, 대학원 소개, 대학원 연구공간, 단국사학회, 고대문명연구소, 한중관계연구소

### ib 국제경영학과 (죽전, 공개)
- 게시판: notice: Notices (218건), jobs: Career Opportunities (51건), activity: Additional Information (11건)
- 뺀 게시판: Discussion Board (글 0건), Gallery (커뮤니티·사진), Tips for Korean Life (글 0건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: Chair’s Message, Department Office

### indsec 사이버보안학과 (죽전, 공개)
- 게시판: notice: 공지사항 (90건), activity: 세미나 (특강) (4건), scholarship: 장학 (12건), jobs: 취업 정보 (133건), rules: 졸업 (4건)
- 데이터: dept_info, professors, curriculum
- 페이지: labs: 소프트웨어보안 연구실, labs_2: 지능형 보안 연구실, labs_3: 융합 시스템 보안 연구실, labs_4: 정보보안 연구실, labs_5: 암호 및 데이터 보안 연구실, labs_6: 지능형 교통 시스템보안 연구실
- 뺀 페이지: 학과장 인사말

### industrialm 산업경영학과(야) (죽전, 공개)
- 게시판: notice: 공지사항 (181건), notice_2: 특성화고졸재직자전형 안내 (3건)
- 뺀 게시판: 졸업시험 문제은행 (글 1건)
- 데이터: curriculum, professors, dept_info
- 페이지: 없음
- 뺀 페이지: 인사말

### koreamusic 국악전공 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: location: 오시는 길
- 뺀 페이지: 전공 인사말

### koreanlitnlang 국어국문학과 (죽전, 공개)
- 게시판: grad: 대학원공지 (31건), notice: 학과 공지사항 (158건), activity: 학과 소식 (3건)
- 뺀 게시판: 대학원 학생회 (커뮤니티·사진), 동문게시판 (커뮤니티·사진), 국어국문학과 사진첩 (커뮤니티·사진), 학생회 공지사항 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: grad_rules: 대학원 내규
- 뺀 페이지: 학과장 인사말, 학과연혁, 학부 학생회 부서 소개, 고전문학부, 학부 학생회 활동, 국어학부, 현대문학부

### law 법학과 (죽전, 공개)
- 게시판: notice: 법과대학 공지 (2,678건), activity: 법과대학 뉴스 (352건)
- 데이터: 없음
- 페이지: 없음

### mathedu 수학교육과 (죽전, 공개)
- 게시판: notice: 학과 공지사항 (65건), archive: 서식자료 (9건)
- 뺀 게시판: 학생회 공지사항 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길

### me 기계공학과 (죽전, 공개)
- 게시판: notice: 학과 공지 (2,037건), archive: 학부자료실 (86건), grad: 대학원 공지 (66건), activity: 학과소식 (216건), jobs: 취업정보 (1,058건), activity_2: 외부행사,경진대회 (107건), grad_2: 대학원자료실 (25건), archive_2: 서식자료실 (4건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 비전, 교육목표, 학부 정규교육과정, 학부 기계공작실, 학부 신입생, 학부 Run2X, 학부 4차 산업혁명 혁신선도대학사업, 학부 미래형자동차 기술융합혁신인재양성사업, 대학원 디저털 제조장비 R&D 전문인력양성사업, 학부 재료실험실, 학부 유체역학실험실, 학부 응용역학실험실, 학부 기계공학종합실험실, 학부 기계CAD실, 학부 공학멘토링, 학부 학생역량, 학부 산학협력 및 취창업, 대학원 AI로봇기반 인간기계협업기술 전문인력양성사업, 대학원 스마트센서 전문인력양성사업, 대학원 친환경자동차 부품개발 R&D 전문인력양성사업

### orchestral-instrument 관현악전공 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 주임교수인사, 연혁

### performance-film 연극전공·영화전공·뮤지컬전공 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학장인사말

### philosophy 철학과 (죽전, 공개)
- 게시판: activity: 융합철학워크숍 (89건), notice: 공지사항 (444건)
- 뺀 게시판: 사진 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장인사말

### piano 피아노전공 (죽전, 공개)
- 게시판: 없음
- 데이터: professors, curriculum
- 페이지: 없음

### polisci 정치외교학과 (죽전, 공개)
- 게시판: activity: 교수동정 (42건), activity_2: 재학생 (96건)
- 뺀 게시판: 졸업생 (글 1건)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 문의 및 위치안내
- 뺀 페이지: 주임교수인사, 연혁

### polymer 고분자공학전공 (죽전, 공개)
- 게시판: notice: 학부 공지 (1,022건), grad: 대학원 공지 (402건), jobs: 채용공고 (772건), activity: 교외활동 (173건), archive: 자료실 (15건), activity_2: 학과 소식 (7건)
- 뺀 게시판: 보유장비 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 전공주임교수 인사말, 생명 및 생체공학, 나노 및 분자 모델링

### sce 융합반도체공학과 (죽전, 공개)
- 게시판: notice: 공지사항 (478건), jobs: 취업정보 (392건)
- 데이터: professors, dept_info, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장인사말, 학부 반도체전공트랙, 학부 차세대시스템반도체설계 전문인력양성사업, 학부 차세대반도체 불량분석 및 품질관리 전문인력양성사업, 학부 시스템반도체 융합전문인력육성사업

### sciedu 과학교육과 (죽전, 공개)
- 게시판: notice: 안내 및 공지사항 (48건), jobs: 교원 및 강사 구인 (114건), archive: 자료실 (4건), activity: 비교과 홍보 게시판 (14건)
- 뺀 게시판: 갤러리 (커뮤니티·사진), 동문 게시판 (커뮤니티·사진), 대학원 게시판 (글 1건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 오시는 길
- 뺀 페이지: 주임교수 인사말, 과학교육과 연혁, 학과 사무실, 학생회 소개

### specialedu 특수교육과 (죽전, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말

### swcon SW융합학부 (죽전, 공개)
- 게시판: notice: 모집안내 (16건), notice_2: 학부공지 (186건), activity: 대외활동공지 (71건), archive: 학사관련 FAQ (21건), archive_2: 자료실 (11건), jobs: 채용정보 (388건)
- 데이터: professors
- 페이지: location: 학부 찾아오시는 길
- 뺀 페이지: 학부 일반소개, 학부 교육목표, 학부 전공소개

### teachertraining 교직교육과 (죽전, 공개)
- 게시판: 없음
- 뺀 게시판: 공지 및 Q&A (커뮤니티·사진), 자료실 (글 0건)
- 데이터: professors
- 페이지: 없음

### trade 무역학과 (죽전, 공개)
- 게시판: notice: 공지사항 (646건), jobs: 취업정보 (51건), activity: 무역학과 대외활동 (19건), notice_2: 학사제도 변경점 (5건), scholarship: 장학금 공지 (16건)
- 뺀 게시판: Q&A (커뮤니티·사진), 취업공지 게시판 (글 2건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말

### urban-real 도시지역계획학전공·부동산학전공 (죽전, 공개)
- 게시판: notice: 공지사항 (296건), activity: 공모전 수상 (12건), jobs: 취업정보 (255건), activity_2: 현직자 초청 특강 (3건)
- 뺀 게시판: 지역답사 (커뮤니티·사진), 교수님과의 소통 (커뮤니티·사진), 장학 (글 0건), 도부인의 밤 (커뮤니티·사진), 입학식/졸업식 (커뮤니티·사진), 기타 행사 (글 1건), 새내기 배움터 (커뮤니티·사진), 연합 MT (커뮤니티·사진), 체육대회 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학부 인사말, 학부연혁, URID, Home

### vocalmusic 성악전공 (죽전, 공개)
- 게시판: 없음
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 음악도서실 (글 0건)
- 데이터: professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 주임교수인사, 전공소개

### animal 동물생명공학전공 (천안, 공개)
- 게시판: 없음
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 연혁, 학사일정

### biology 생명과학전공 (천안, 공개)
- 게시판: notice: 공지사항 (45건), activity: 홍보게시판 (6건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 식물면역학 실험실, 계통분류학 실험실, 분자암노화 실험실, 발생분화 실험실, 식물발달생물학 실험실, 생리생화학 실험실, 신경교세포 실험실, 유전체 실험실, 분자의과학 실험실

### biomedical 임상병리학과 (천안, 공개)
- 게시판: 없음
- 뺀 게시판: 학생회 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음

### biomedical20 의생명시스템학전공 (천안, 공개)
- 게시판: notice: 공지사항 (9건)
- 데이터: professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 학사일정, 학과 사진

### chemistry 화학과 (천안, 공개)
- 게시판: notice: 학부 공지사항 (410건), grad: 대학원 공지사항 (143건), archive: 자료실 (21건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길

### china 중국학전공 (천안, 공개)
- 게시판: notice: 공지사항 (98건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info, curriculum, professors
- 페이지: career: 졸업후 진로, location: 찾아오시는 길
- 뺀 페이지: 동아리 소개

### cosmedmaterials 코스메디컬소재학과 (천안, 공개)
- 게시판: notice: 공지사항 (31건)
- 데이터: dept_info, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 교수소개

### craft 공예전공 (천안, 공개)
- 게시판: notice: 학과공지 (2건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 주임교수 인사

### crops 식량생명공학전공 (천안, 공개)
- 게시판: notice: 공지사항 (6건)
- 데이터: dept_info, professors
- 페이지: 없음
- 뺀 페이지: 주임교수 인사, 연혁, 학과특성화, 분자육종실험실, 식물분자생물학실험실, 기능성식물신소재실험실, 식물대사공학실험실

### dentalhygiene 치위생학과 (천안, 공개)
- 게시판: notice: 공지사항 (41건), activity: 치위생학과 소식 (18건), activity_2: 실습현황 (8건), jobs: 취업정보 (68건)
- 뺀 게시판: 사진첩 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 인사말

### dentistry 치의예과·치의학과 (천안, 공개)
- 게시판: notice: 학사공지 (142건), scholarship: 장학공지 (132건), archive: 입학전형 (16건), notice_2: 공지사항 (10건), activity: 새소식 (67건), activity_2: 치과대학 연구동향 (30건), activity_3: 치과대학소식 (13건), activity_4: 언론홍보 (9건)
- 뺀 게시판: 동아리 게시판 (커뮤니티·사진), 동문게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진), 세미나/강연 (글 1건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 오시는길
- 뺀 페이지: 학장 인사말, 교육철학과 목표, 구강미생물학교실, 구강내과학교실, 역량과 평가, 학생회 게시판, 구강병리학교실, 구강생리학교실, 구강생화학교실, 구강조직학교실, 구강해부학교실, 생체재료학교실, 치과약리학교실, 재생치의학교실, 구강악안면외과학교실, 소아치과학교실, 영상치의학교실, 예방치과학교실, 치과교정학교실, 치과마취학교실, 치과보존학교실, 치과보철학교실, 치주과학교실, 통합치의학교실

### dkcw 문예창작과 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 교육목표와 연계성

### dkfrance 프랑스학전공 (천안, 공개)
- 게시판: notice: 공지사항 (22건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: career: 졸업 후 진로
- 뺀 페이지: 학장인사말, 전공연혁, 교육목표, 국내 외 교류, 동아리

### dkme 경영공학과 (천안, 공개)
- 게시판: activity: 수상실적 및 활동 (19건), notice: 학과 공지사항 (104건), scholarship: 취업/공모/장학 (88건), activity_2: 학과소식 (8건)
- 뺀 게시판: 동아리소개 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과연혁, 마이크로전공

### dkuhort 환경원예학전공 (천안, 공개)
- 게시판: notice: 공지사항 (67건), activity: 학과소식 (6건), jobs: 취업 정보 (14건), activity_2: 대외활동 (4건)
- 뺀 게시판: 원예작물유전육종실험실 (글 0건), 화훼원예학실험실 (글 1건), 스마트원예ICT융합연구실 (글 0건), 원예작물병리학실험실 (글 0건), 대학원 (글 0건), HAG (글 1건), WON-YE FC (글 0건)
- 데이터: dept_info, professors, curriculum
- 페이지: graduation: 졸업요건, career: 주요 진로 분야, certificate: 전공 관련 자격증

### dkwelfare 사회복지학과 (천안, 공개)
- 게시판: notice: 공지사항 (15건)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 찾아오시는 길

### dsm 스포츠경영학과 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 학과 연혁

### energy 에너지공학과 (천안, 공개)
- 게시판: notice: 학부공지 (103건), grad: 대학원공지 (56건), scholarship: 장학/취업공지 (52건), archive: 자료실 (5건)
- 데이터: dept_info, professors, curriculum
- 페이지: labs: 에너지소재공정연구실, labs_2: 전기화학응용소재연구실, labs_3: 차세대에너지소재소자연구실, labs_4: 환경에너지나노소재연구실, labs_5: 미래에너지시스템전기화학공학연구실
- 뺀 페이지: 기능성에너지소재실험실, 관련사이트

### english 영어과 (천안, 공개)
- 게시판: notice: 공지사항 (110건), jobs: 채용게시판 (43건)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말, Home

### ere 식품자원경제학과 (천안, 공개)
- 게시판: 없음
- 뺀 게시판: 자유게시판 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말

### fineart 서양화전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학사일정

### food 식품공학과 (천안, 공개)
- 게시판: notice: 공지게시판 (238건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진)
- 데이터: dept_info, curriculum, professors
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 학사일정, 연혁, 수여학위 명칭, 교육목표, 프로그램 학습성과, 학교생활, 식품⦁나노시스템공학실험실, 향미화학실험실, 기능성식품미생물학실험실, 식품소재가공학실험실, 스마트식품공정실험실, 교육목표와의 연관성, 공학인증과의 부합성, 평가체계

### foodnutrition 식품영양학과 (천안, 공개)
- 게시판: notice: 학부 공지 (16건), grad: 일반대학원 공지 (16건), grad_2: 교육대학원 공지 (30건), jobs: 취업 (33건)
- 뺀 게시판: 동문회 소식 (커뮤니티·사진), 자유롭게말해요 (커뮤니티·사진), 자격증 정보 (역할 불명), 식영photo (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음

### german 독일학전공 (천안, 공개)
- 게시판: 없음
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: curriculum_guide: 이수로드맵
- 뺀 페이지: 학과 내 학생활동, 찾아오기, 교수님 한 말씀, 추천도서, 비교과교육과정

### globalhankook 글로벌한국어과 (천안, 공개)
- 게시판: notice: 공지사항 (89건), activity: 글로벌한국어과 소식 (18건)
- 뺀 게시판: 자료실 (글 1건), FAQ (글 0건)
- 데이터: dept_info, professors
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 인사말, 교과과정, 학사일정

### healthadmin 보건행정학과 (천안, 공개)
- 게시판: archive: 보건의료정보관리인증 (10건), activity: 보건행정소식 (203건), jobs: 채용공고 (18건), activity_2: 실습현황 (20건)
- 뺀 게시판: 동문소식 (커뮤니티·사진), 취업현황 (글 1건), 사진첩 (커뮤니티·사진), Q&A (커뮤니티·사진)
- 데이터: dept_info, professors
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 연혁 및 개괄

### int_sports 국제스포츠전공 (천안, 공개)
- 게시판: 없음
- 데이터: professors, curriculum
- 페이지: 없음
- 뺀 페이지: 주임교수 인사말, 전공 연혁

### japanese 일본학전공 (천안, 공개)
- 게시판: notice: 공지사항 (562건), archive: 자료실 (18건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 인사말

### jazzperformance 재즈퍼포먼스전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말

### joso 조소전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 주임교수 인사, 연혁

### landscape 녹지조경학전공 (천안, 공개)
- 게시판: grad: 대학원 활동 (11건), capstone: 2025년 졸업작품전 (16건), capstone_2: 2024년 졸업작품전 (18건), archive: 수업자료실 (11건), notice: 공지사항 (51건), activity: 대외활동 (13건)
- 뺀 게시판: 조경설계경관 연구실 (글 1건), 공간생태 연구실 (글 2건), 생태 관측 연구실 (글 1건), 대학원(천안) (글 1건), 대학원(죽전) (글 1건), 이전 졸업작품전 (글 1건), 전공로드맵 (글 2건), 갤러리 (커뮤니티·사진), 전공활동 (글 2건), 학생회 (커뮤니티·사진), CLUB418 (커뮤니티·사진), FCLA (역할 불명), Re:U (글 2건), 그린톡 (역할 불명)
- 데이터: dept_info, professors
- 페이지: labs: 관광 및 지역계획 연구실
- 뺀 페이지: 주임교수인사, 학사일정

### mathematics 수학과 (천안, 공개)
- 게시판: notice: 수학과게시판 (7건), archive: 교육자료실 (3건)
- 뺀 게시판: 행사사진 (커뮤니티·사진)
- 데이터: dept_info, professors
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말, 대학원 박희철(해석학), 대학원 김도형(미분기하학), 대학원 정호윤(대수학), 대학원 최재길(해석학)

### microbiology 미생물학전공 (천안, 공개)
- 게시판: notice: 공지사항 (42건), activity: News (127건), scholarship: 장학 및 취업 (5건)
- 데이터: dept_info, professors, curriculum
- 페이지: grad_labs: 대학원 미생물유전체연구실험실(한규동)
- 뺀 페이지: 인사말, 대학원 분자바이러스학실험실(정용태), 대학원 분자미생물학실험실(오만환), 대학원 진균생명공학실험실(김성환), 대학원 생물정보학실험실(강근수)

### middleeasternstudies 중동학전공 (천안, 공개)
- 게시판: notice: 공지게시판 (333건), jobs: 취업게시판 (72건)
- 뺀 게시판: 정치 (overrides), 경제 (글 1건), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: career: 졸업 후 진로, location: 찾아오시는 길
- 뺀 페이지: 인사말, 동아리소개

### mongol 몽골학전공 (천안, 공개)
- 게시판: notice: 공지사항 (95건), activity: 몽골학과 뉴스 (10건)
- 데이터: professors
- 페이지: location: 찾아오시는 길, graduation: 졸업요건
- 뺀 페이지: 학과소개, 인사말, 학사일정, 교육과정, 행사사진

### mse 신소재공학과 (천안, 공개)
- 게시판: notice: 공지사항 (106건), activity: News (51건), archive: 자료실 (73건), scholarship: 장학&취업정보 (153건)
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, curriculum, professors
- 페이지: career: 진로/활동분야, location: 찾아오시는 길, grad_labs: 대학원 나노구조재료 공정 연구실(주수현), grad_labs_2: 대학원 재료전산모사 연구실(최용석)
- 뺀 페이지: 연혁, 교직이수과정, 마이크로전공, 대학원 나노재료실험실(윤종원), 대학원 신소재에너지실험실(문태호)

### newmusicdku 뮤직테크놀러지전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학사일정

### nursing 간호학과 (천안, 공개)
- 게시판: archive: 평가체계표 (10건), notice: 공지사항 (393건), archive_2: 학과자료실 (25건), jobs: 취업정보 (78건), notice_2: 게시판 (57건), archive_3: 학습성과 (10건), notice_3: 공지사항 (9건), grad: 공지사항(대학원) (77건), grad_2: 공지사항(보건복지대학원) (8건)
- 뺀 게시판: 행사/세미나 사진 (커뮤니티·사진), 출판논문 (overrides), 원우회게시판 (글 1건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학장 인사말, 교육시설, 대학원 소개, 대학원 소개, 학생회, 관련사이트, 소장인사말, 연구소 소개, 행사/세미나 연혁, 동문회 소개, 정관, 동문회 임원, 동문회 사업, 역대 회장단, 대학원 입학전형, 대학원 입학전형, 대학원 학사운영, 대학원 교과과정, 대학원 원우회

### oriental 동양화전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학장 인사말

### pharm 제약공학과 (천안, 공개)
- 게시판: 없음
- 데이터: professors, dept_info, curriculum
- 페이지: 없음

### pharmacy 약학과 (천안, 공개)
- 게시판: notice: 학부 공지사항 (47건), grad: 대학원 공지사항 (48건), jobs: 취업·모집 공고 (627건), activity: 행사·학술세미나/동향 및 수상 (43건)
- 뺀 게시판: 갤러리 (커뮤니티·사진), 동아리 게시판 (커뮤니티·사진), 학생회 게시판 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 오시는길
- 뺀 페이지: 일반소개, 학장 인사말, 연구소, 실무실습 안내, 실무실습비 지출 내역, 교육지원시설

### physical_therapy 물리치료학과 (천안, 공개)
- 게시판: 없음
- 뺀 게시판: 자유게시판 (커뮤니티·사진), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: career: 취업 및 진로
- 뺀 페이지: 학과연혁

### physics 물리학과 (천안, 공개)
- 게시판: notice: 학사 게시판 (5건), activity: 홍보 게시판 (10건)
- 뺀 게시판: 갤러리 (커뮤니티·사진)
- 데이터: dept_info, curriculum, professors
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말

### portuguese 포르투갈브라질학전공 (천안, 공개)
- 게시판: notice: 공지사항 (63건)
- 뺀 게시판: 서식 (글 1건), 갤러리 (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사, 연혁, 학사일정

### psychology 심리학과·심리치료학과 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors
- 페이지: 없음

### publicadm 공공정책학과·공공정책학과(야) (천안, 공개)
- 게시판: notice: 공지사항 (29건), jobs: 취업정보 (161건), activity: 프로그램홍보 (7건)
- 뺀 게시판: 자료 (글 2건)
- 데이터: professors, dept_info
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 마이크로전공, 연혁, 학생회, 학과 동아리, 행사 안내

### rokmcms 해병대군사학과 (천안, 공개)
- 게시판: activity: 학과행사 (72건), activity_2: 뉴스 및 포럼 (32건), activity_3: 교육 및 세미나 (13건), activity_4: 특성화 활동 (7건), notice: 공지사항 (501건)
- 뺀 게시판: Q & A (커뮤니티·사진)
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 해병대군사학과 訓

### russia 러시아학전공 (천안, 공개)
- 게시판: notice: 공지사항 (131건), notice_2: 주요학사공지 (18건), archive: 자료실 (4건), jobs: 취업정보 (13건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말, 학과연혁

### singersongwriting 싱어송라이팅전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말

### spain 스페인중남미학전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 학과장 인사말, 학사일정, 연혁

### sports 생활체육학과 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 학과장 인사말, 학사일정

### sportsscience 운동처방재활전공 (천안, 공개)
- 게시판: 없음
- 데이터: dept_info, professors, curriculum
- 페이지: 없음
- 뺀 페이지: 인사말

### taekwondo 태권도전공 (천안, 공개)
- 게시판: 없음
- 데이터: professors, curriculum
- 페이지: 없음
- 뺀 페이지: 주임교수 인사말, 학과 연혁

### vietnam 베트남학전공 (천안, 공개)
- 게시판: notice: 공지사항 (489건), jobs: 취업 정보 (13건), activity: 베트남 뉴스 (576건)
- 데이터: dept_info, professors, curriculum
- 페이지: location: 찾아오시는 길
- 뺀 페이지: 인사말
