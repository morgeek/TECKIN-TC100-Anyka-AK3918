import os

patch_path = '/Users/keegrom/Developer/TECKIN-TC100-Anyka-AK3918/patches/kernel-6.6/linux-6.6-ak3918-step6-audio.patch'
audio_dir = '/Users/keegrom/Developer/TECKIN-TC100-Anyka-AK3918/patches/kernel-6.6/audio'

def file_to_patch(src_path, dst_path):
    with open(src_path, 'r', errors='ignore') as f:
        content = f.read()
    lines = content.splitlines()
    header = [
        f'diff --git a/{dst_path} b/{dst_path}',
        'new file mode 100644',
        '--- /dev/null',
        f'+++ b/{dst_path}',
        f'@@ -0,0 +1,{len(lines)} @@'
    ]
    patch_lines = ['+' + line for line in lines]
    return '\n'.join(header + patch_lines) + '\n'

kconfig_patch = '''diff --git a/sound/arm/Kconfig b/sound/arm/Kconfig
--- a/sound/arm/Kconfig
+++ b/sound/arm/Kconfig
@@ -29,4 +29,15 @@ config SND_PXA2XX_AC97
 	  Say Y or M if you want to support any AC97 codec attached to
 	  the PXA2xx AC97 interface.
 
+config SND_AK_PCM
+	tristate "Anyka ADC/DAC sound driver"
+	select SND_PCM
+	help
+	  ALSA sound driver for the AK ADC/DAC.
+
+config CODEC_AK39
+	bool "AK39 internal codec"
+	depends on SND_AK_PCM
+	default y
+
 endif	# SND_ARM
'''

makefile_patch = '''diff --git a/sound/arm/Makefile b/sound/arm/Makefile
--- a/sound/arm/Makefile
+++ b/sound/arm/Makefile
@@ -11,3 +11,9 @@ snd-pxa2xx-lib-$(CONFIG_SND_PXA2XX_LIB_AC97)	+= pxa2xx-ac97-lib.o
 
 obj-$(CONFIG_SND_PXA2XX_AC97)	+= snd-pxa2xx-ac97.o
 snd-pxa2xx-ac97-objs		:= pxa2xx-ac97.o
+
+obj-$(CONFIG_SND_AK_PCM)	+= snd-akpcm.o
+snd-akpcm-objs			:= ak_pcm.o
+
+obj-$(CONFIG_CODEC_AK39)	+= snd-codec-ak39.o
+snd-codec-ak39-objs		:= ak39_codec.o
'''

dts_patch = '''diff --git a/arch/arm/boot/dts/anyka/ak3918ev300-tc100.dts b/arch/arm/boot/dts/anyka/ak3918ev300-tc100.dts
--- a/arch/arm/boot/dts/anyka/ak3918ev300-tc100.dts
+++ b/arch/arm/boot/dts/anyka/ak3918ev300-tc100.dts
@@ -169,4 +169,14 @@ vi: video-input@20000000 {
 		anyka,sharepin-or = <0x40000710 0x0 0x01450525 0x100>;
 	};
+
+	adc_dac: codec@20110000 {
+		compatible = "anyka,ak39ev330-adc-dac";
+		reg = <0x08000000 0x100>,
+		      <0x20110000 0x8008>;
+		interrupts = <6>, <7>;
+		speak-gpios = <&gpio0 14 0>;
+		speak-gpios-en = <1>;
+		status = "okay";
+	};
 };
'''

parts = [
    file_to_patch(os.path.join(audio_dir, 'ak_pcm.h'), 'include/sound/ak_pcm.h'),
    file_to_patch(os.path.join(audio_dir, 'ak_codec.h'), 'sound/arm/ak_codec.h'),
    file_to_patch(os.path.join(audio_dir, 'ak_pcm.c'), 'sound/arm/ak_pcm.c'),
    file_to_patch(os.path.join(audio_dir, 'ak39_codec.c'), 'sound/arm/ak39_codec.c'),
    kconfig_patch,
    makefile_patch,
    dts_patch
]

with open(patch_path, 'w') as f:
    f.write(''.join(parts))

print(f'Generated {patch_path}, size: {os.path.getsize(patch_path)} bytes')
