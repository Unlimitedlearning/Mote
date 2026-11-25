/* 主题在首屏绘制前定下来，否则深色系统会先闪一下白 */
try{
 var _t=localStorage.getItem('mote-theme');
 if(_t!=='light'&&_t!=='dark')_t=(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';
 document.documentElement.dataset.theme=_t;
}catch(e){}
