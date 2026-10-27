"""Run with /usr/bin/python3 (system UNO) after starting the local LibreOffice listener."""
from pathlib import Path
import sys,time
import uno
from com.sun.star.beans import PropertyValue

HERE=Path(__file__).resolve().parent
NAME='Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa'
def prop(k,v):
 p=PropertyValue();p.Name=k;p.Value=v;return p
ctx=uno.getComponentContext()
resolver=ctx.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',ctx)
for attempt in range(30):
 try:
  remote=resolver.resolve('uno:socket,host=127.0.0.1,port=20173;urp;StarOffice.ComponentContext');break
 except Exception:
  if attempt==29:raise
  time.sleep(.3)
desktop=remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',remote)
url=uno.systemPathToFileUrl(str(HERE/(NAME+'.docx')))
doc=desktop.loadComponentFromURL(url,'_blank',0,(prop('Hidden',True),prop('UpdateDocMode',3)))
try:
 for _ in range(3):
  doc.refresh()
  indexes=doc.getDocumentIndexes()
  for i in range(indexes.getCount()):indexes.getByIndex(i).update()
  doc.getTextFields().refresh()
 doc.storeAsURL(url,(prop('FilterName','Office Open XML Text'),prop('Overwrite',True)))
 doc.storeToURL(uno.systemPathToFileUrl(str(HERE/(NAME+'.pdf'))),(prop('FilterName','writer_pdf_Export'),prop('Overwrite',True)))
 print('DOCX and PDF finalized; pages:',doc.CurrentController.PageCount)
finally:doc.close(True)
