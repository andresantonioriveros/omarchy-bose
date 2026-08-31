import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Ui

// Brand mark, generic device, and mode icons for the popup.
Item {
  id: root

  property string variant: "logo"
  property real iconSize: 20
  property real iconWidth: iconSize
  property real iconHeight: iconSize
  property color color: Color.foreground
  property string fontFamily: "JetBrainsMono Nerd Font"

  implicitWidth: iconWidth
  implicitHeight: iconHeight

  readonly property real markLeft: 33.009
  readonly property real markWidth: 44.822
  readonly property real markTop: 1.054
  readonly property real markHeight: 24.967
  readonly property string markPath: "M73.8 1.054L45.295 1.054L33.009 21.892L5.88 21.892L5.8935314 26.021L60.629 26.021C64.266 26.021 65.445 24.251 66.232 22.875L69.18 17.764C69.967 16.388 69.967 14.815 68.394 13.931C69.97 13.931 72.129 12.85 73.407 10.589L76.356 5.576C77.831 3.119 76.061 1.054 73.8 1.054zM59.155 17.863L57.68 20.221C57.287 21.008 56.599 21.892 54.928 21.892L47.654 21.892L51.392 15.602L58.466 15.602C59.744 15.602 59.744 16.781 59.155 17.863zM65.347 7.443L63.872 9.802C63.479 10.589 62.791 11.473 61.12 11.473L53.846 11.473L57.581 5.183L64.658 5.183C65.937 5.183 65.937 6.362 65.347 7.443z"
  readonly property real markScale: Math.min(iconWidth / markWidth, iconHeight / markHeight)
  readonly property bool usesFontGlyph: variant === "earbuds" || variant === "headphones"
  readonly property string fontGlyph: variant === "earbuds" ? "󱡏" : "󰋋"

  function pathForVariant(kind) {
    if (kind === "mark") {
      return root.markPath
    }
    if (kind === "mode") {
      return "M3.4 11.7V10.6C3.4 5.65 7.2 2 12 2S20.6 5.65 20.6 10.6V11.7H18.55V10.6C18.55 6.82 15.65 4.1 12 4.1S5.45 6.82 5.45 10.6V11.7H3.4ZM2.2 11.2H6.05V17.55H2.2V11.2ZM17.95 11.2H21.8V17.55H17.95V11.2ZM8 13.1H16V14.9H8V13.1ZM9.35 16.15H14.65V18H9.35V16.15Z"
    }
    if (kind === "modeQuiet" || kind === "modeHigh") {
      return "M12 2.2C6.59 2.2 2.2 6.59 2.2 12S6.59 21.8 12 21.8 21.8 17.41 21.8 12 17.41 2.2 12 2.2ZM12 4C16.42 4 20 7.58 20 12S16.42 20 12 20 4 16.42 4 12 7.58 4 12 4ZM12 7.1A2.1 2.1 0 1 0 12 11.3A2.1 2.1 0 0 0 12 7.1ZM7.5 17.3C7.85 15.15 9.7 13.55 12 13.55S16.15 15.15 16.5 17.3C15.22 18.14 13.69 18.6 12 18.6S8.78 18.14 7.5 17.3Z"
    }
    if (kind === "modeAware" || kind === "modeLow") {
      return "M11.2 2.1H12.8V5.2H11.2V2.1ZM4.32 5.45L5.45 4.32L7.65 6.52L6.52 7.65L4.32 5.45ZM2.1 11.2H5.2V12.8H2.1V11.2ZM4.32 18.55L6.52 16.35L7.65 17.48L5.45 19.68L4.32 18.55ZM11.2 18.8H12.8V21.9H11.2V18.8ZM16.35 17.48L17.48 16.35L19.68 18.55L18.55 19.68L16.35 17.48ZM18.8 11.2H21.9V12.8H18.8V11.2ZM16.35 6.52L18.55 4.32L19.68 5.45L17.48 7.65L16.35 6.52ZM12 7.2A4.8 4.8 0 1 0 12 16.8A4.8 4.8 0 0 0 12 7.2Z"
    }
    if (kind === "modeRelax") {
      return "M12 2.2C6.59 2.2 2.2 6.59 2.2 12S6.59 21.8 12 21.8 21.8 17.41 21.8 12 17.41 2.2 12 2.2ZM12 4C16.42 4 20 7.58 20 12S16.42 20 12 20 4 16.42 4 12 7.58 4 12 4ZM8.7 10.1H10.3V11.7H8.7V10.1ZM13.7 10.1H15.3V11.7H13.7V10.1ZM8 14.3C8.9 16.1 10.2 17 12 17S15.1 16.1 16 14.3L14.55 13.7C14 14.8 13.16 15.5 12 15.5S10 14.8 9.45 13.7L8 14.3Z"
    }
    if (kind === "modeImmersion") {
      return "M12 7.1A2.1 2.1 0 1 0 12 11.3A2.1 2.1 0 0 0 12 7.1ZM7.5 17.8C7.85 15.45 9.7 13.8 12 13.8S16.15 15.45 16.5 17.8C15.22 18.45 13.69 18.8 12 18.8S8.78 18.45 7.5 17.8ZM5.45 8.25C3.9 9.25 3 10.75 3 12.5S3.9 15.75 5.45 16.75L6.35 15.5C5.25 14.75 4.7 13.75 4.7 12.5S5.25 10.25 6.35 9.5L5.45 8.25ZM18.55 8.25L17.65 9.5C18.75 10.25 19.3 11.25 19.3 12.5S18.75 14.75 17.65 15.5L18.55 16.75C20.1 15.75 21 14.25 21 12.5S20.1 9.25 18.55 8.25Z"
    }
    if (kind === "modeCinema") {
      return "M3.2 5.1H20.8V7.3H3.2V5.1ZM4.2 8.1H19.8V19.4H4.2V8.1ZM5.1 5.1L7.15 7.3H9.55L7.5 5.1H5.1ZM10.1 5.1L12.15 7.3H14.55L12.5 5.1H10.1ZM15.1 5.1L17.15 7.3H19.55L17.5 5.1H15.1ZM10 10.7V16.8L15.2 13.75L10 10.7Z"
    }
    if (kind === "modeOff") {
      return "M12 2.2C6.59 2.2 2.2 6.59 2.2 12S6.59 21.8 12 21.8 21.8 17.41 21.8 12 17.41 2.2 12 2.2ZM12 4C16.42 4 20 7.58 20 12S16.42 20 12 20 4 16.42 4 12 7.58 4 12 4ZM4.05 2.85L21.15 19.95L19.95 21.15L2.85 4.05L4.05 2.85Z"
    }
    if (kind === "noise") {
      return "M12 2.2C6.59 2.2 2.2 6.59 2.2 12S6.59 21.8 12 21.8 21.8 17.41 21.8 12 17.41 2.2 12 2.2ZM12 4C16.42 4 20 7.58 20 12S16.42 20 12 20 4 16.42 4 12 7.58 4 12 4ZM8.55 10.3H9.95V13.7H8.55V10.3ZM11.3 8.2H12.7V15.8H11.3V8.2ZM14.05 10.3H15.45V13.7H14.05V10.3Z"
    }
    return "M14.052 10.589a.69.69 0 0 0-.588.332l-.54.915c-.114.19.036.399.235.399h1.873l-.336.568a.274.274 0 0 1-.24.139h-.29a.113.113 0 0 1-.102-.164c.035-.062.112-.19.112-.19h-1.699l-.246.418c-.115.194.038.405.232.405h3.174a.692.692 0 0 0 .598-.34c.12-.206.405-.69.527-.896.123-.205-.032-.41-.228-.41h-1.873l.347-.586a.276.276 0 0 1 .231-.123h.292c.095 0 .135.102.105.155-.03.053-.117.199-.117.199h1.696l.254-.43c.094-.16-.023-.392-.24-.392h-3.18.003zm-1.344 0H9.537c-.23 0-.47.12-.592.329-.124.207-1.13 1.911-1.24 2.096-.109.185.042.397.236.397h3.177c.255 0 .48-.141.592-.33.111-.188 1.13-1.915 1.237-2.094.106-.18-.03-.4-.24-.4v.002zm-1.598.636c-.045.076-.89 1.505-.936 1.585a.276.276 0 0 1-.236.134h-.295c-.094 0-.138-.102-.102-.163l.94-1.592a.274.274 0 0 1 .235-.13h.296c.085 0 .143.091.097.167l.001-.001zm-2.919-.636H4.61l-1.39 2.354H0v.47h6.598a.69.69 0 0 0 .596-.336l.41-.697c.085-.145-.004-.331-.164-.379a.703.703 0 0 0 .583-.329c.115-.193.298-.506.402-.682a.266.266 0 0 0-.234-.4v-.001zM6.29 12.402l-.243.411a.267.267 0 0 1-.233.132h-.9l.419-.708h.857a.11.11 0 0 1 .099.166zm.694-1.178-.242.41a.266.266 0 0 1-.233.131h-.9l.418-.708h.858c.09 0 .14.093.098.167h.001zm11.194-.635-1.667 2.823h4.042l.276-.469h-2.345l.418-.707h2.345l.278-.47H19.18l.418-.709H24v-.468h-5.822z"
  }

  Item {
    visible: root.variant === "mark"
    x: (root.width - root.markWidth * root.markScale) / 2
    y: (root.height - root.markHeight * root.markScale) / 2
    width: root.markWidth * root.markScale
    height: root.markHeight * root.markScale
    clip: true

    Shape {
      width: 215
      height: 27
      x: -root.markLeft * root.markScale
      y: -root.markTop * root.markScale
      transform: Scale {
        xScale: root.markScale
        yScale: root.markScale
      }
      preferredRendererType: Shape.CurveRenderer
      layer.enabled: false

      ShapePath {
        fillColor: root.color
        strokeWidth: -1
        fillRule: ShapePath.WindingFill
        PathSvg {
          path: root.markPath
        }
      }
    }
  }

  Shape {
    visible: root.variant !== "mark" && !root.usesFontGlyph
    width: 24
    height: 24
    x: (root.width - root.iconWidth) / 2
    y: (root.height - root.iconHeight) / 2
    transform: Scale {
      xScale: root.iconWidth / 24
      yScale: root.iconHeight / 24
    }
    preferredRendererType: Shape.CurveRenderer
    layer.enabled: false

    ShapePath {
      fillColor: root.color
      strokeWidth: -1
       fillRule: root.variant.indexOf("mode") === 0 || root.variant === "noise"
         ? ShapePath.OddEvenFill : ShapePath.WindingFill
      PathSvg {
        path: root.pathForVariant(root.variant)
      }
    }
  }

  OpticalGlyph {
    visible: root.usesFontGlyph
    anchors.fill: parent
    text: root.fontGlyph
    fontFamily: root.fontFamily
    fontSize: root.iconSize
    color: root.color
  }
}
