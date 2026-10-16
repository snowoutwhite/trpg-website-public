import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  tseslint.configs.recommended,
  // 只取 essential（正确性规则）；排版分行一类的强意见规则不启用，交给编辑器/人。
  pluginVue.configs['flat/essential'],
  {
    // 安全扫描脚本跑在 Node 里（`npm run security`），给它 node 全局，
    // 否则 js.configs.recommended 的 no-undef 会把 process/console 全判成未定义。
    files: ['scripts/**/*.mjs'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    rules: {
      /* 安全红线：用户内容一律用插值渲染。
         Markdown 渲染将来由带白名单 sanitize 的专门组件承担，届时只在该组件内定点豁免。 */
      'vue/no-v-html': 'error',
      /* 会话 Cookie 方案不需要在浏览器存储里放任何凭据 */
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: '禁止用 localStorage 存凭据或用户数据；会话由后端 Cookie 承担。' },
      ],
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
)
