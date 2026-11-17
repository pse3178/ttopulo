"""Conservative Korean OCR import for alternating-column scanned exam books.

This parser NEVER trusts an OCR-read answer as a grading key. All imported
questions require manual verification before grading is enabled.
"""
import re
import shutil
import subprocess

import fitz
from PIL import Image, ImageOps, ImageEnhance
import pytesseract

CIRCLES = '①②③④⑤⑥⑦⑧⑨⑩'
QUESTION = re.compile(r'^\s*(\d{1,3})\s*[.．,]?\s+(?=[가-힣A-Za-z0-9(\"“])')
ANSWER = re.compile(r'^\s*(\d{1,3})\s*(?:정답|정담|정답\s*[:：]|정담\s*[:：])', re.I)
OPTION = re.compile(r'^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩⓵⓶⓷⓸⓹]|[©®@Oo0Q]|[Oo0Q][a-zA-Z]|\([0-9OoQ]\)?|\d[)．])\s*')
SECTION = re.compile(r'\b2\s*[-–]\s*[1-9]\s+[가-힣]')


def ocr_available():
    if not shutil.which('tesseract'):
        return False
    try:
        return 'kor' in pytesseract.get_languages(config='')
    except (OSError, pytesseract.TesseractError):
        return False


def render(page, dpi=185):
    mat=fitz.Matrix(dpi/72,dpi/72)
    pm=page.get_pixmap(matrix=mat,alpha=False)
    return Image.frombytes('RGB', (pm.width, pm.height), pm.samples)


def region_text(image, box):
    w,h=image.size
    cut=image.crop((int(box[0]*w),int(box[1]*h),int(box[2]*w),int(box[3]*h)))
    cut=ImageEnhance.Contrast(ImageOps.grayscale(cut)).enhance(1.6)
    return pytesseract.image_to_string(cut,lang='kor+eng',config='--psm 6')


def page_regions(page, page_index):
    # This particular scan has opposite facing-page layouts.
    # PDF page 1: solutions left, questions right.
    # PDF page 2: questions left, solutions right; repeat.
    if page_index % 2 == 0:
        return (.385,.065,.985,.93),(.035,.065,.385,.93)
    return (.035,.065,.66,.93),(.645,.065,.985,.93)


def normalized_lines(txt):
    return [re.sub(r'\s+', ' ',s).strip() for s in txt.splitlines() if s.strip()]


def find_numbered(lines, pattern, low, high):
    chunks=[]; cur=None
    for line in lines:
        m=pattern.match(line)
        num=int(m.group(1)) if m else None
        if num is not None and low<=num<=high and (cur is None or num>cur[0]):
            if cur:chunks.append(cur)
            cur=(num,[line[m.end():].strip()])
        elif cur:
            cur[1].append(line)
    if cur:chunks.append(cur)
    return dict(chunks)


def split_question(lines, num):
    prompt=[]; options=[]; seen_option=False
    for line in lines:
        if SECTION.search(line) and len(line)<55:continue
        m=OPTION.match(line)
        if m:
            seen_option=True
            options.append(line[m.end():].strip())
        elif seen_option and options:
            # Wrapped options are longer; text is appended to preceding choice.
            options[-1] += ' '+line
        else:
            prompt.append(line)
    # OCR can miss the symbols: do not create unsupported options.
    return ' '.join(prompt).strip(),options


def extract_scanned_pdf(pdf_data, start_page=1, end_page=5, progress=None):
    if not ocr_available():
        raise RuntimeError('한국어 OCR 엔진이 준비되지 않았어. Streamlit packages.txt 설정을 확인해 줘.')
    doc=fitz.open(stream=pdf_data,filetype='pdf')
    if not (1<=start_page<=end_page<=len(doc)):
        raise ValueError('페이지 범위를 확인해 줘.')
    if end_page-start_page+1>12:
        raise ValueError('서버 부담을 줄이기 위해 한 번에 최대 12페이지씩 인식할 수 있어.')
    out=[]; previous=0
    for index in range(start_page-1,end_page):
        im=render(doc[index]);qbox,abox=page_regions(doc[index],index)
        qlines=normalized_lines(region_text(im,qbox))
        # First scanned spread: OCR may confuse orange 1 and 2 with | and 7.
        if index == 0:
            qlines=[re.sub(r'^\|\s+(?=21세)', '1 ', s) for s in qlines]
            qlines=[re.sub(r'^7\s+(?=18세)', '2 ', s) for s in qlines]
        alines=normalized_lines(region_text(im,abox))
        # Search 1..999, but filter to plausible ascending question numbers.
        qblocks=find_numbered(qlines,QUESTION,1,999)
        ablocks=find_numbered(alines,ANSWER,1,999)
        for num,lines in qblocks.items():
            if num <= previous or num > previous+10 and previous>0:continue
            prompt,option_lines=split_question(lines,num)
            if len(prompt)<12:continue
            if not (2<=len(option_lines)<=7):
                # Keep the stem, mark missing/ambiguous choices for editing.
                option_lines=option_lines[:10]
            ans=ablocks.get(num,[])
            raw_answer=' '.join(ans).strip()
            # Do NOT guess circled numbers from OCR. Answer must be supplied by user.
            notes='OCR 추출: 원본 PDF p.%d. 문제·선지·해설·정답을 반드시 원본과 대조해 줘.'%(index+1)
            if raw_answer:
                notes+='\n정답/해설 OCR 원문: '+raw_answer[:1400]
            out.append(dict(section='모성간호학',number=num,page=index+1,
                prompt=prompt,options=[dict(label=CIRCLES[i],text=s) for i,s in enumerate(option_lines[:10])],
                answer_text='',answer_indices=[],explanation=raw_answer[:3000],
                notes=notes,needs_review=True,uid=f'OCR-{index+1}-{num}'))
            previous=num
        if progress:progress(index-start_page+2,end_page-start_page+1)
    return out
