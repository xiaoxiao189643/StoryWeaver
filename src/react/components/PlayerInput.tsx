// ============================================================
// PlayerInput —— 底部玩家干预输入框 (含暂停推演功能)
// ============================================================
import { useEffect, useState } from "react";
import { wsClient } from "../../core/WebSocketClient";
import { useGameState } from "../hooks/useGameState";
import { globalEventBus } from "../../core/EventBus";

export function PlayerInput() {
  const [inputText, setInputText] = useState("");
  const [sending, setSending] = useState(false);
  const { isPaused } = useGameState();

  useEffect(() => {
    const unsub = globalEventBus.on("intervention_result", () => setSending(false));
    return unsub;
  }, []);

  const handleSubmit = () => {
    if (!inputText.trim() || sending) return;

    console.log("[PlayerInput] 发送:", inputText, "WS state:", wsClient["ws"]?.readyState);

    if ((window as any).simulateSetupInput) {
      console.log("[PlayerInput] → simulateSetupInput");
      (window as any).simulateSetupInput(inputText);
    } else {
      console.log("[PlayerInput] → sendIntervention");
      setSending(true);
      wsClient.sendIntervention("all", "persuasion", inputText);
    }

    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  // 切换暂停/继续状态
  const togglePause = () => {
    wsClient.setGameControl(isPaused ? "resume" : "pause");
    console.log(isPaused ? "[系统]: 请求继续推演" : "[系统]: 请求暂停故事");
  };

  return (
    <div className="input-wrapper" style={{ width: "100%", display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div className="input-console">
        <span className="iconfont icon-xuehuayuanjiao xuehuafrosty"></span>
        <input
          type="text"
          className="input-box"
          placeholder="在此输入你的指令或设定，参与重塑世界..."
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
        />


        {/* 暂停/继续按钮（iconfont 图标） */}
        <button
          className={`input-btn-icon ${isPaused ? "paused" : ""}`}
          onClick={togglePause}
          title={isPaused ? "继续推演" : "暂停推演，思考对策"}
        >

          <span className={`iconfont ${isPaused ? "icon-zanting1 frosty-text" : "icon-zanting frosty-text"}`}></span>
        </button>

        {/* <button className="iconfont" onClick={handleSubmit} disabled={sending}>
          {sending ? "处理中" : "发送"}
        </button> */}
        <button className={`input-btn-round iconfont ${sending ? "icon-sangedian frosty-text" : "icon-send frosty-text"}`}
          onClick={handleSubmit}
          disabled={sending}
          aria-label={sending ? "处理中" : "发送"}
          style={{ border: 'none', outline: 'none'}}
        />
  
        
      </div>

      <div className="input-hint-text">
        {isPaused ? (
          <span style={{ color: "#ef4444", fontWeight: "bold" }}>时空已冻结 · 发送指令会立即推进一轮回应</span>
        ) : (
          <>按下 <span style={{ color: "#3b83f6c4", fontWeight: "bold" }}>Enter</span> 发送指令 · 你的每一个字都在重塑这个世界</>
        )}
      </div>
    </div>
  );
}