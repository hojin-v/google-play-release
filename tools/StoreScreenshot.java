import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

/** Preserves a full, real device capture on an opaque 1080x1920 store canvas. */
public class StoreScreenshot {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("input.png output.png");
        BufferedImage src = ImageIO.read(new File(args[0]));
        if (src == null) throw new IllegalArgumentException("invalid source capture");
        BufferedImage dst = new BufferedImage(1080, 1920, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = dst.createGraphics();
        g.setColor(new Color(0xF6F7F9));
        g.fillRect(0, 0, 1080, 1920);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
        double scale = Math.min(1080.0 / src.getWidth(), 1920.0 / src.getHeight());
        int w = (int) Math.round(src.getWidth() * scale), h = (int) Math.round(src.getHeight() * scale);
        g.drawImage(src, (1080 - w) / 2, (1920 - h) / 2, w, h, null);
        g.dispose();
        ImageIO.write(dst, "png", new File(args[1]));
    }
}
