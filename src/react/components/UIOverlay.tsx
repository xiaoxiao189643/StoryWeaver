// ============================================================
// UIOverlay —— 根 UI 覆盖层 (含拖拽侧边栏 + 分区字体自定义 + 全屏修复)
// ============================================================
import React, { useState, useEffect, useRef, useCallback } from "react";
import { NarrativeStage } from "./NarrativeStage";
import { ObservationDeck } from "./ObservationDeck";
import { TimelinePanel } from "./TimelinePanel";
import { PlayerInput } from "./PlayerInput";


export function UIOverlay() {
  // 面板开关状态
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // 面板宽度状态
  const [historyWidth, setHistoryWidth] = useState(280);
  const [sidebarWidth, setSidebarWidth] = useState(340);

  // 字体大小控制状态
  const [fsStage, setFsStage] = useState(16);
  const [fsHistory, setFsHistory] = useState(13);
  const [fsSidebar, setFsSidebar] = useState(14);
  const [showSettings, setShowSettings] = useState(false);
  const [isFooterOpen, setIsFooterOpen] = useState(true);

  // 拖拽状态与 Ref
  const [isDragging, setIsDragging] = useState<'left' | 'right' | null>(null);
  const dragRef = useRef<{ type: 'left' | 'right' | null }>({ type: null });

  // 开始拖拽
  const startDrag = (type: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current.type = type;
    setIsDragging(type);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  // 拖拽中计算新宽度
  const onDrag = useCallback((e: MouseEvent) => {
    if (dragRef.current.type === 'left') {
      const newWidth = Math.max(200, Math.min(e.clientX, window.innerWidth / 2));
      setHistoryWidth(newWidth);
    } else if (dragRef.current.type === 'right') {
      const newWidth = Math.max(250, Math.min(window.innerWidth - e.clientX, window.innerWidth / 2));
      setSidebarWidth(newWidth);
    }
  }, []);

  // 结束拖拽
  const stopDrag = useCallback(() => {
    dragRef.current.type = null;
    setIsDragging(null);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
    }
    return () => {
      document.removeEventListener('mousemove', onDrag);
      document.removeEventListener('mouseup', stopDrag);
    };
  }, [isDragging, onDrag, stopDrag]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth <= 900) {
        setIsHistoryOpen(false);
        setIsSidebarOpen(false);
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 全屏模式监听 - 修复历史栏交互
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isFullscreen = !!document.fullscreenElement;
      const layout = document.querySelector('.sw-layout');
      const history = document.querySelector('.sw-history');
      const sidebar = document.querySelector('.sw-sidebar');

      if (isFullscreen) {
        layout?.classList.add('fullscreen-mode');
        // 强制刷新历史栏和侧边栏的交互
        if (history) {
          (history as HTMLElement).style.pointerEvents = 'auto';
          (history as HTMLElement).style.zIndex = '1000';
        }
        if (sidebar) {
          (sidebar as HTMLElement).style.pointerEvents = 'auto';
          (sidebar as HTMLElement).style.zIndex = '1000';
        }
        // 强制重新计算布局
        setTimeout(() => {
          window.dispatchEvent(new Event('resize'));
        }, 100);
      } else {
        layout?.classList.remove('fullscreen-mode');
        if (history) {
          (history as HTMLElement).style.pointerEvents = '';
          (history as HTMLElement).style.zIndex = '';
        }
        if (sidebar) {
          (sidebar as HTMLElement).style.pointerEvents = '';
          (sidebar as HTMLElement).style.zIndex = '';
        }
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  return (
    <div
      className={`sw-layout ${isDragging ? "dragging" : ""}`}
      style={{
        '--fs-stage': `${fsStage}px`,
        '--fs-history': `${fsHistory}px`,
        '--fs-sidebar': `${fsSidebar}px`
      } as React.CSSProperties}
    >

      {/* --- 顶栏 --- */}
      <header className="sw-header">
        <div className="sw-title">
          <button className="sw-settings" onClick={() => setIsHistoryOpen(!isHistoryOpen)}>
            {isHistoryOpen ? (
              <span className="iconfont icon-zuozhankai1 frosty-text"></span>
            ) : (
              <span className="iconfont icon-youzhankai frosty-text"></span>
            )}
          </button>
     
          <span className="storyweaver-text">Story Weaver</span>
        </div>
        <svg style={{ display: 'none' }}>
          <filter id="frost-filter">
            <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="4" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise" scale="5" xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </svg>

        {/* 右侧控制区 */}
        <div style={{ display: 'flex', gap: '20px', alignItems: 'center', position: 'relative' }}>

          {/* 设置按钮 */}
          <button
            className={`sw-settings ${showSettings ? 'active-setting' : ''}`}
            onClick={() => setShowSettings(!showSettings)}
          >
            <span className="iconfont icon-yuedupianhao frosty-text"></span>
          </button>

          <button
            className={`sw-settings ${isFooterOpen ? 'active-setting' : ''}`}
            onClick={() => setIsFooterOpen(!isFooterOpen)}
          >
            <span className="iconfont icon-qiehuanmianbandibu frosty"></span>
          </button>

          {/* 字体设置下拉悬浮窗 */}
          {showSettings && (
            <div className="font-settings-panel">
              <div style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 'bold', marginBottom: '12px', borderBottom: '1px solid #e2e8f0', paddingBottom: '6px' }}>
                字体大小调节 (Px)
              </div>

              <div className="fs-control-row">
                <span>🎭 主舞台对话</span>
                <input type="range" min="14" max="24" value={fsStage} onChange={e => setFsStage(Number(e.target.value))} />
                <span className="fs-value">{fsStage}</span>
              </div>

              <div className="fs-control-row">
                <span>📊 右侧详情卡</span>
                <input type="range" min="12" max="20" value={fsSidebar} onChange={e => setFsSidebar(Number(e.target.value))} />
                <span className="fs-value">{fsSidebar}</span>
              </div>

              <div className="fs-control-row">
                <span>📜 左侧历史栏</span>
                <input type="range" min="11" max="18" value={fsHistory} onChange={e => setFsHistory(Number(e.target.value))} />
                <span className="fs-value">{fsHistory}</span>
              </div>

              <button
                className="fs-reset-btn"
                onClick={() => { setFsStage(16); setFsHistory(13); setFsSidebar(14); }}
              >
                恢复默认
              </button>
            </div>
          )}

            <button className="sw-settings1" onClick={() => setIsSidebarOpen(!isSidebarOpen)}>
              {isSidebarOpen ? (
                <>
                  <span className="iconfont icon-youzhankai frosty-text" style={{ marginRight: 6 }} />
                </>
              ) : (
                <>
                  <span className="iconfont icon-zuozhankai1 frosty-text" style={{ marginRight: 6 }} />
                </>
              )}
            </button>
       
        </div>
      </header>

      {/* --- 左侧：分级历史故事记录 --- */}
      <aside className={`sw-history ${isHistoryOpen ? "" : "collapsed"}`} style={{ width: isHistoryOpen ? historyWidth : 0 }}>
        <div className="history-inner">
          <div className="history-title-main frosty">历史叙事足迹</div>
          <TimelinePanel />
        </div>
      </aside>

      {/* 左侧拖拽条 */}
      {isHistoryOpen && <div className={`resizer-l ${isDragging === 'left' ? 'active' : ''}`} onMouseDown={startDrag('left')} />}

      {/* --- 中间：主叙事舞台 --- */}
      <main className="sw-stage">
        <NarrativeStage />
      </main>

      {/* 右侧拖拽条 */}
      {isSidebarOpen && <div className={`resizer-r ${isDragging === 'right' ? 'active' : ''}`} onMouseDown={startDrag('right')} />}

      {/* --- 右侧：故事详情面板 --- */}
      <aside className={`sw-sidebar ${isSidebarOpen ? "" : "collapsed"}`} style={{ width: isSidebarOpen ? sidebarWidth : 0 }}>
        <div className="sidebar-inner">
          <ObservationDeck />
        </div>
      </aside>

      {/* --- 底栏：指令输入 --- */}
      {isFooterOpen && (
        <footer className="sw-footer">
          <PlayerInput />
        </footer>
      )}
    </div>
  );
}