<script setup lang="ts">
/** 认证五页共用的分栏外壳（v2 `login.html` / `signup.html` 的 `.auth` + `.auth-art` + `.auth-form`）。 */
import BlurStage from '../components/BlurStage.vue'

withDefaults(
  defineProps<{
    /** 左侧美术的图片地址（调用方从 `lib/rule-art.ts` 取）。 */
    art?: string
    /** 压在美术上的眼标，如 `SIGN IN`。 */
    kicker?: string
    /** 压在美术上的一句话。 */
    line?: string
    /** 右下角的美术出处小字（规则系统名），可不给。 */
    credit?: string
    /** 只渲染内容，不渲染分栏与美术 —— 嵌进另一个 AuthShell 的表单栏时用（登录页的忘记密码面板）。 */
    bare?: boolean
  }>(),
  { bare: false },
)
</script>

<template>
  <div v-if="bare" class="auth__pane"><slot /></div>
  <div v-else class="auth">
    <BlurStage class="auth__art" as="section" :file="art" tone="dark" alt="" aria-hidden="true">
      <div class="auth__art-body">
        <p class="auth__art-line">
          <span v-if="kicker" class="u-kicker auth__art-kicker">{{ kicker }}</span>
          {{ line }}
        </p>
        <span v-if="credit" class="auth__art-credit">{{ credit }}</span>
      </div>
    </BlurStage>
    <section class="auth__form">
      <div class="auth__inner u-rise"><slot /></div>
    </section>
  </div>
</template>

<style scoped>
.auth {
  display: grid;
  /* 抵掉 .l-main 的上留白，让美术横幅贴住页头（v2 的分栏也是紧挨顶栏） */
  margin-top: calc(var(--sp-5) * -1);
}

.auth__art {
  /* display:grid 让 BlurStage 内部的内容层（.c-blur-stage__body）成为撑满整块的网格项，
     .auth__art-body 才能靠 inset:0 贴住四边 */
  display: grid;
  min-height: 190px;
  margin-bottom: var(--sp-6);
  /* < 768px 的 --pad 是 20px 字面值（tokens.css），抵掉 .l-main 左右留白即满幅横幅 */
  margin-inline: calc(var(--pad) * -1);
}

/* `BlurStage` 的前景图是**替换元素**：只给 `inset: 0` 而不给宽高时，绝对定位的替换元素
   按固有尺寸排版、`right`/`bottom` 被忽略（CSS 2.1 §10.3.8），所以图只占顶上一条、
   下面露出模糊底。这里定死宽高让 `object-fit: cover` 真正生效。
   **这是 BlurStage.vue 自身该修的**（凡是舞台比例与图不同的地方都中招），
   本波不许动 `src/components/*`，先在调用方兜住，已在报告里登记。 */
.auth__art :deep(.c-blur-stage__fg) {
  width: 100%;
  height: 100%;
}

.auth__art-body {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: var(--sp-5);
  color: var(--on-dark);
  /* v2 `.auth-art::after` 的压暗层。BlurStage 自己的遮罩在前景图**下面**（z-index -1 对 0），
     压不住清晰图，白字直接落在亮色美术（dnd / overview 都很亮）上会读不清，这一层由调用方补。
     叠两层是因为最深的现成令牌 `--scrim-2` 只有 60% 不透明度，而 v2 的 `.auth-art::after`
     收在 83%（#0a1614d4）—— 两层相乘约 84%，不写字面色值就能到位。
     缺一个更深的 `--scrim-3` 令牌，已在报告里登记（本波不改 tokens.css）。
     手机横幅只有 190px 高、文字块落在 45% 处，所以压暗要来得比桌面早。 */
  /* 复检 2026-09-22：signup@375 文字行压在 DND 金色高光上只有 2.29:1，遮罩提前到 4% 并用 --scrim-3（83%）收底 */
  background:
    linear-gradient(180deg, transparent 4%, var(--scrim-2) 36%, var(--scrim-3)),
    linear-gradient(180deg, transparent 30%, var(--scrim-3));
}

.auth__art-line {
  max-width: 16em;
  /* 下边留一行：最后一行文字不要贴着右下角那行出处小字 */
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-xl);
  line-height: var(--lh-body);
  /* v2 是 -.02em，令牌里最近的一档是 --ls-section(-0.03em) */
  letter-spacing: var(--ls-section);
  text-shadow: var(--text-shadow-dark);
}

.auth__art-kicker {
  display: block;
  margin-bottom: var(--sp-3);
  color: var(--on-dark-kicker);
  text-shadow: var(--text-shadow-dark);
}

.auth__art-credit {
  position: absolute;
  right: var(--sp-5);
  bottom: var(--sp-3);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark-3);
  text-shadow: var(--text-shadow-dark);
}

.auth__form {
  display: grid;
  place-items: center;
}

.auth__inner {
  width: 100%;
  /* v2 的表单净宽是 376，本站认证卡统一 460（与 .c-sheet--narrow 同宽） */
  max-width: 460px;
}

@media (min-width: 768px) {
  /* 收进版心，整块变成一张圆角面板 */
  .auth {
    margin-top: 0;
    overflow: hidden;
    background: var(--white);
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
  }

  .auth__art {
    min-height: 220px;
    margin-bottom: 0;
    margin-inline: 0;
  }

  /* 桌面分栏上美术高 600+，文字落在 75% 处，顶部可以更亮（v2 的观感） */
  .auth__art-body {
    background:
      linear-gradient(180deg, transparent 32%, var(--scrim-1) 58%, var(--scrim-2)),
      linear-gradient(180deg, transparent 62%, var(--scrim-2));
  }

  .auth__art-line {
    max-width: 20em;
    font-size: var(--fs-2xl);
  }

  .auth__form {
    padding: var(--sp-7) var(--sp-5);
  }
}

@media (min-width: 1200px) {
  /* 左美术 / 右表单（v2 .auth 的 1.02fr .98fr） */
  .auth {
    grid-template-columns: 1.02fr 0.98fr;
    min-height: 600px;
  }

  .auth__art {
    min-height: 0;
  }

  .auth__art-body {
    padding: var(--sp-6) var(--sp-5);
  }

  .auth__form {
    padding: var(--sp-7) var(--sp-6);
  }
}
</style>
