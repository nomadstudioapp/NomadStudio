# Nomad Studio — Portrait & Fashion Pose Presets

A curated collection of photographic and editorial pose presets designed for prompt injection, Mix flows (clothing transfer, character consistency), and Create portraits.

---

## 1. Classic Portrait & Studio

Standard studio poses tailored for corporate headshots, personal branding, and beauty portraits.

| Preset Key | UI Label | Prompt Snippet |
| :--- | :--- | :--- |
| `three_quarter_turn` | **Three-Quarter Turn** | `standing in a relaxed three-quarter turn, shoulders angled at 45 degrees, face turned naturally toward the camera` |
| `over_shoulder` | **Over the Shoulder** | `body turned away from the camera, glancing back over the shoulder with a gentle natural gaze` |
| `subtle_head_tilt` | **Subtle Head Tilt** | `front-facing portrait with a subtle head tilt, soft relaxed neck line and natural direct eye contact` |
| `side_profile` | **Side Profile** | `clean side profile view, defined jawline, looking straight ahead into the distance` |
| `hand_on_chin` | **Hand on Chin** | `one hand lightly resting under the chin, thoughtful relaxed portrait pose` |
| `crossed_arms` | **Confident Crossed Arms** | `standing with arms lightly crossed over chest, confident friendly posture, upright shoulders` |
| `hands_clasped_front` | **Hands Clasped Front** | `hands gently clasped in front of body at waist level, poised and professional posture` |

---

## 2. Fashion & Editorial Lookbook

Editorial stances optimized for clothing drape, apparel catalogs, and fashion campaigns.

| Preset Key | UI Label | Prompt Snippet |
| :--- | :--- | :--- |
| `contrapposto` | **Contrapposto (Weight Shift)** | `classic contrapposto stance, weight shifted naturally onto one hip, one leg slightly bent and relaxed` |
| `hand_on_hip` | **Hand on Hip** | `one hand resting on the hip, torso slightly angled, editorial fashion posture` |
| `hands_in_pockets` | **Hands in Pockets** | `standing tall with both hands casually in front pockets, elbows slightly bent, relaxed tailored stance` |
| `one_hand_in_pocket` | **One Hand in Pocket** | `one hand casually tucked into pocket, other arm resting naturally at the side` |
| `leaning_wall` | **Leaning Against Wall** | `leaning back casually against a neutral studio wall, one foot slightly raised, relaxed slouch` |
| `high_stool_seated` | **Seated on High Stool** | `seated on a minimalist studio high stool, one foot resting on the rung, elongated posture` |
| `jacket_over_shoulder` | **Jacket Over Shoulder** | `holding a tailored jacket slung over one shoulder with one finger, walking stance` |
| `lapel_hold` | **Holding Lapels** | `both hands lightly holding the lapels of the jacket or coat, showcasing the garment drape and fit` |
| `collar_adjust` | **Adjusting Collar** | `one hand subtly touching the shirt collar or necklace, high fashion gesture` |

---

## 3. Lifestyle & Candid

Natural, dynamic poses for travel photography, street style, and candid moments.

| Preset Key | UI Label | Prompt Snippet |
| :--- | :--- | :--- |
| `mid_stride_walk` | **Mid-Stride Street Walk** | `captured mid-stride walking down the street, natural forward motion, relaxed swinging arms` |
| `walking_turn_back` | **Walking & Turning Back** | `walking away from camera and looking back over shoulder with a spontaneous smile` |
| `looking_away` | **Looking Away (Candid)** | `candid moment looking away to the side, natural candid expression as if unaware of the camera` |
| `seated_on_steps` | **Seated on Steps** | `sitting casually on stone steps, leaning forward with elbows on knees, authentic street snapshot` |
| `leaning_railing` | **Leaning on Railing** | `leaning forward against a balcony railing with both forearms resting, looking out at the scene` |
| `adjusting_watch` | **Adjusting Watch / Cuff** | `natural candid pose looking down while adjusting a watch or sleeve cuff with both hands` |
| `wind_in_hair` | **Wind in Hair Turn** | `slight turn into the breeze, subtle hair motion, looking back with a spontaneous smile` |
| `cafe_table_lean` | **Seated at Café Table** | `seated at an outdoor cafe table with one arm resting near a cup, relaxed observational posture` |

---

## 4. Close-Up & Details

Cropped poses focusing on hands, jewelry, makeup, and expression.

| Preset Key | UI Label | Prompt Snippet |
| :--- | :--- | :--- |
| `hands_framing_face` | **Hands Framing Face** | `intimate close-up portrait with fingertips softly touching temples or jawline, beauty crop` |
| `looking_down` | **Looking Down (Reflective)** | `face angled slightly down with eyelashes visible, soft contemplative expression` |
| `upward_angle` | **Slight Upward Angle** | `subtle low-angle perspective, chin raised slightly, commanding yet relaxed editorial look` |

---

## 5. Implementation Example in Nomad Studio Flows

When passing the selected preset to an SDXL / Flux / Refine / Mix prompt template:

```text
[Subject Base Prompt], [Preset Prompt Snippet], natural fabric drape, realistic wrinkles and seams, photorealistic studio lighting, high detail skin texture --ar 3:4
```

### JSON Structure for UI Presets (Dropdowns / Selectors)

```json
{
  "categories": [
    {
      "id": "studio",
      "name": "Classic Studio & Portrait",
      "presets": [
        { "id": "three_quarter_turn", "label": "Three-Quarter Turn", "snippet": "standing in a relaxed three-quarter turn, shoulders angled at 45 degrees, face turned naturally toward the camera" },
        { "id": "over_shoulder", "label": "Over the Shoulder", "snippet": "body turned away from the camera, glancing back over the shoulder with a gentle natural gaze" },
        { "id": "subtle_head_tilt", "label": "Subtle Head Tilt", "snippet": "front-facing portrait with a subtle head tilt, soft relaxed neck line and natural direct eye contact" },
        { "id": "crossed_arms", "label": "Confident Crossed Arms", "snippet": "standing with arms lightly crossed over chest, confident friendly posture, upright shoulders" }
      ]
    },
    {
      "id": "fashion",
      "name": "Fashion & Lookbook",
      "presets": [
        { "id": "contrapposto", "label": "Contrapposto Stance", "snippet": "classic contrapposto stance, weight shifted naturally onto one hip, one leg slightly bent and relaxed" },
        { "id": "hand_on_hip", "label": "Hand on Hip", "snippet": "one hand resting on the hip, torso slightly angled, editorial fashion posture" },
        { "id": "hands_in_pockets", "label": "Both Hands in Pockets", "snippet": "standing tall with both hands casually in front pockets, elbows slightly bent, relaxed tailored stance" },
        { "id": "leaning_wall", "label": "Leaning Against Wall", "snippet": "leaning back casually against a neutral studio wall, one foot slightly raised, relaxed slouch" },
        { "id": "high_stool_seated", "label": "Seated on High Stool", "snippet": "seated on a minimalist studio high stool, one foot resting on the rung, elongated posture" }
      ]
    },
    {
      "id": "lifestyle",
      "name": "Lifestyle & Street",
      "presets": [
        { "id": "mid_stride_walk", "label": "Mid-Stride Walk", "snippet": "captured mid-stride walking down the street, natural forward motion, relaxed swinging arms" },
        { "id": "looking_away", "label": "Looking Away (Candid)", "snippet": "candid moment looking away to the side, natural candid expression as if unaware of the camera" },
        { "id": "seated_on_steps", "label": "Seated on Steps", "snippet": "sitting casually on stone steps, leaning forward with elbows on knees, authentic street snapshot" },
        { "id": "adjusting_watch", "label": "Adjusting Watch / Cuff", "snippet": "natural candid pose looking down while adjusting a watch or sleeve cuff with both hands" }
      ]
    }
  ]
}
```
