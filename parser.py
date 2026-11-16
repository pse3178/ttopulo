"""PDF two-column quiz extraction; conservative: preserves source, marks uncertainty."""
import re
import fitz

Q_RE=re.compile(r'^문제\s*(\d+)\s*[.．:]\s*(.*)')
OPTION_RE=re.compile(r'^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)')
ANSWER_RE=re.compile(r'^(?:정답|교수님\s*제시\s*정답)\s*:\s*(.*)')
HEADER_RE=re.compile(r'^\[(혈액\s*[,·]\s*림프계|호흡기계|호흡계)\]')
CIRCLES='①②③④⑤⑥⑦⑧⑨⑩'

def page_lines(page):
    # Text extraction from two-column landscape slide; read left column first.
    bounds=page.rect.width / 2
    blocks=[b for b in page.get_text('blocks') if len(b)>4 and isinstance(b[4],str) and b[4].strip()]
    for side in (0,1):
        selected=sorted((b for b in blocks if (b[0]<bounds)==(side==0)), key=lambda b:(round(b[1],1),b[0]))
        for b in selected:
            for line in b[4].splitlines():
                line=line.strip()
                if line: yield line

def join_lines(lines):
    if not lines:return ''
    out=lines[0]
    for line in lines[1:]:
        # A Korean syllable split at page/line break should not gain a space.
        if out.endswith(('-', '→', '/', '·')):out+=line
        elif re.search(r'[가-힣]$',out) and re.match(r'^[가-힣]',line) and not re.search(r'[.!?。:]$',out):out+=line
        else:out+=' '+line
    return out.strip()

def extract_pdf(pdf_data):
    doc=fitz.open(stream=pdf_data,filetype='pdf')
    result=[];section='미분류';current=None;warnings=[]
    def finish():
        if not current:return
        q=current
        q['prompt']=join_lines(q.pop('_prompt'))
        q['options']=[{'label':o['label'],'text':join_lines(o['lines'])} for o in q.pop('_options')]
        q['answer_text']=join_lines(q.pop('_answer'))
        q['explanation']=join_lines(q.pop('_explanation'))
        q['notes']=join_lines(q.pop('_notes'))
        q['answer_indices']=list(dict.fromkeys(CIRCLES.index(c) for c in re.findall('['+CIRCLES+']',q['answer_text'])))
        q['needs_review']=not q['answer_indices'] or len(q['options'])<2 or any(x in (q['answer_text']+' '+q['notes']+' '+q['explanation']) for x in ('문항 오류','선지 누락','검토:','두 질환을 확정','모두 가능','수정이 필요'))
        if len(q['answer_indices'])==1 and q['answer_indices'][0]>=len(q['options']):q['needs_review']=True
        if len(q['answer_indices'])>1:q['needs_review']=True
        q['uid']=f"{q['section']}-{q['number']}-{len(result)}"
        result.append(q)
    mode='prompt'
    for page_num,page in enumerate(doc,1):
        for line in page_lines(page):
            if line=='병리학 기말고사 퀴즈':continue
            h=HEADER_RE.match(line)
            if h:
                section='호흡기계' if '호흡' in h.group(1) else '혈액·림프계'
                continue
            m=Q_RE.match(line)
            if m:
                finish()
                current={'section':section,'number':int(m.group(1)),'page':page_num,'_prompt':[m.group(2)],'_options':[],'_answer':[],'_explanation':[],'_notes':[]}
                mode='prompt';continue
            if not current:continue
            om=OPTION_RE.match(line)
            if om and mode in ('prompt','options'):
                current['_options'].append({'label':om.group(1),'lines':[om.group(2)]});mode='options';continue
            am=ANSWER_RE.match(line)
            if am:
                # preserve author's original answer as primary, professor key as annotation if both appear
                if line.startswith('교수님 제시 정답:') and current['_answer']:
                    current['_notes'].append(line)
                    mode='notes'
                elif line.startswith('교수님 제시 정답:'):
                    current['_answer'].append(am.group(1));mode='answer'
                    current['_notes'].append('교수님 제시 정답 기준')
                else:
                    current['_answer'].append(am.group(1));mode='answer'
                continue
            if line.startswith(('피드백:','해설:')):
                current['_explanation'].append(line.split(':',1)[1].strip());mode='explanation';continue
            if line.startswith(('검토:','원문에 기재','원문 피드백','두 응고','따라서','①과 ②가 중복','아. 정답은')):
                current['_notes'].append(line);mode='notes';continue
            if mode=='options' and current['_options']:
                current['_options'][-1]['lines'].append(line)
            elif mode=='answer':current['_answer'].append(line)
            elif mode=='explanation':current['_explanation'].append(line)
            elif mode=='notes':current['_notes'].append(line)
            else:current['_prompt'].append(line)
    finish()
    return result
