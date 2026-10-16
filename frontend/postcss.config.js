import autoprefixer from 'autoprefixer'

/** 微信内置浏览器的 WebKit 版本偏旧，交给 autoprefixer 按 browserslist 补前缀。 */
export default {
  plugins: [autoprefixer()],
}
