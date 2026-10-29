// 播放器图标（inline SVG，Material 风格 path，无额外依赖）。
import { defineComponent, h } from 'vue'

function makeIcon(name: string, pathData: string[], viewBox = '0 0 24 24') {
  return defineComponent({
    name,
    props: {
      size: { type: Number, default: 18 },
    },
    setup(props) {
      return () =>
        h(
          'svg',
          {
            width: props.size,
            height: props.size,
            viewBox,
            fill: 'currentColor',
            'aria-hidden': 'true',
            focusable: 'false',
          },
          pathData.map((d) => h('path', { d })),
        )
    },
  })
}

export const PlayIcon = makeIcon('PlayIcon', ['M8 5v14l11-7z'])
export const PauseIcon = makeIcon('PauseIcon', ['M6 19h4V5H6v14zm8-14v14h4V5h-4z'])
export const SkipPrevIcon = makeIcon('SkipPrevIcon', ['M6 6h2v12H6zm3.5 6l8.5 6V6z'])
export const SkipNextIcon = makeIcon('SkipNextIcon', ['M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z'])
export const SequentialIcon = makeIcon('SequentialIcon', [
  'M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z',
])
export const SingleIcon = makeIcon('SingleIcon', [
  'M6 5v14l8-7zM18 6h2v12h-2z',
])
export const RepeatAllIcon = makeIcon('RepeatAllIcon', [
  'M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z',
])
export const RepeatOneIcon = makeIcon('RepeatOneIcon', [
  'M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-4-2V9h-1l-2 1v1h1.5v4H13z',
])
export const ShuffleIcon = makeIcon('ShuffleIcon', [
  'M10.59 9.17L5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41l-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z',
])
