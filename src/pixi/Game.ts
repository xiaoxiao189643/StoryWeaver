// ============================================================
// src/pixi/Game.ts —— 视觉特效引擎 (无地图纯特效版)
// ============================================================
import * as PIXI from "pixi.js";
import { globalEventBus } from "../core/EventBus";
import { WSMessageType } from "../types/api";

export class GameEngine {
  public app!: PIXI.Application;
  private effectContainer!: PIXI.Container;

  public async init(containerElement: HTMLElement) {
    this.app = new PIXI.Application();
    
    // 初始化全屏透明画布，覆盖在 React UI 下方或作为底层背景
    await this.app.init({
      resizeTo: window,
      backgroundAlpha: 0, // 透明背景，让 React UI 也能透出来
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    containerElement.appendChild(this.app.canvas);

    // 特效层容器
    this.effectContainer = new PIXI.Container();
    this.app.stage.addChild(this.effectContainer);

    console.log("[Pixi Engine] 底层沉浸特效引擎初始化完毕。");

    this.setupEffectListeners();
  }

  // 监听后端下发的氛围调度指令
  private setupEffectListeners() {
    globalEventBus.on(WSMessageType.DIRECTOR_ATMOSPHERE, (payload: any) => {
      console.log("[Pixi Engine] 收到跨媒体调度指令:", payload);
      
      if (payload.screen_effect === "shake_hard") {
        this.triggerScreenShake();
      } else if (payload.screen_effect === "flash_red") {
        this.triggerFlashRed();
      }
    });

    globalEventBus.on(WSMessageType.STORY_INITIALIZED, () => {
      this.playWorldCreationEffect();
    });
  }

  // 特效：全屏剧烈震动
  private triggerScreenShake() {
    const intensity = 15;
    let frames = 20;
    
    const shakeTicker = () => {
      if (frames <= 0) {
        this.app.stage.x = 0;
        this.app.stage.y = 0;
        this.app.ticker.remove(shakeTicker);
        return;
      }
      this.app.stage.x = (Math.random() - 0.5) * intensity;
      this.app.stage.y = (Math.random() - 0.5) * intensity;
      frames--;
    };
    
    this.app.ticker.add(shakeTicker);
  }

  // 特效：全屏泛红
  private triggerFlashRed() {
    const redOverlay = new PIXI.Graphics();
    redOverlay.rect(0, 0, this.app.screen.width, this.app.screen.height);
    redOverlay.fill({ color: 0xff0000, alpha: 0.4 });
    this.effectContainer.addChild(redOverlay);

    let alpha = 0.4;
    const fadeTicker = () => {
      alpha -= 0.01;
      redOverlay.alpha = alpha;
      if (alpha <= 0) {
        this.effectContainer.removeChild(redOverlay);
        redOverlay.destroy();
        this.app.ticker.remove(fadeTicker);
      }
    };
    this.app.ticker.add(fadeTicker);
  }

  // 特效：创世完成时的时空重塑粒子流
  private playWorldCreationEffect() {
    console.log("[Pixi Engine] 播放创世时空重塑动效...");
  }
}

export const gameEngine = new GameEngine();