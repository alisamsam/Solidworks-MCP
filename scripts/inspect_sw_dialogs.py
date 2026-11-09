"""Read visible SolidWorks window/dialog titles for stalled COM diagnosis."""
import json,win32gui,win32process
rows=[]
def visit(h,_):
    if not win32gui.IsWindowVisible(h):return
    title=win32gui.GetWindowText(h)
    if not title:return
    pid=win32process.GetWindowThreadProcessId(h)[1]
    if pid!=55632:return
    children=[]
    win32gui.EnumChildWindows(h,lambda c,p:children.append({'class':win32gui.GetClassName(c),'text':win32gui.GetWindowText(c)}),None)
    rows.append({'window':h,'title':title,'class':win32gui.GetClassName(h),'children':[c for c in children if c['text']][:60]})
win32gui.EnumWindows(visit,None)
print(json.dumps(rows,ensure_ascii=True,indent=2))
